# -*- coding: utf-8 -*-
"""网易云音乐 API 客户端 - 使用 pyncm 加密与连接池复用"""
import asyncio
import logging
import threading
import time
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit
import httpx

logger = logging.getLogger('pipeline.netease_api')

# ── 用 pyncm 装饰器定义每日推荐接口 ──
from pyncm.apis import WeapiCryptoRequest

_pyncm_lock = threading.RLock()
_VALID_AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wav"}


@WeapiCryptoRequest
def _GetDailyRecommendSongs():
    """获取每日推荐歌曲"""
    return "/weapi/v3/discovery/recommend/songs", {}


def _init_pyncm(cookie: str = ""):
    from pyncm import GetCurrentSession
    with _pyncm_lock:
        session = GetCurrentSession()
        if cookie:
            session.cookies.set("MUSIC_U", cookie, domain=".music.163.com")
        else:
            for c in list(session.cookies):
                if c.name == "MUSIC_U":
                    try:
                        session.cookies.clear(c.domain, c.path, c.name)
                    except KeyError:
                        pass


class NeteaseAPI:
    _PLAYLIST_CACHE_TTL = 300.0

    def __init__(self, cookie: str = ""):
        self.cookie = cookie
        self._http_client: httpx.AsyncClient | None = None
        self._playlist_cache: dict[int, tuple[float, list[int]]] = {}
        _init_pyncm(cookie)

    def _get_http_client(self) -> httpx.AsyncClient:
        """获取或初始化复用的异步 HTTP 客户端连接池"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=15.0),
                follow_redirects=True,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            )
        return self._http_client

    async def aclose(self):
        """关闭底层 HTTP 客户端连接池"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    async def _run_sync(self, func, *args, **kwargs):
        def _locked_call():
            with _pyncm_lock:
                return func(*args, **kwargs)

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(_locked_call))

    async def get_daily_recommend(self) -> list:
        """获取每日推荐歌曲"""
        if not self.cookie:
            raise Exception("每日推荐需要 MUSIC_U cookie")
        data = await self._run_sync(_GetDailyRecommendSongs)
        if data.get("code") != 200:
            raise Exception(f"API error {data.get('code')}: {data.get('msg', data.get('message', ''))}")
        songs = data.get("data", {}).get("dailySongs", [])
        if not songs:
            songs = data.get("recommend", [])
        return self._parse_songs(songs)

    async def search_songs(self, keyword: str, limit: int = 20, offset: int = 0) -> dict:
        from pyncm.apis.cloudsearch import GetSearchResult
        data = await self._run_sync(GetSearchResult, keyword, limit=limit, offset=offset)
        result = data.get("result", {})
        songs_raw = result.get("songs", [])
        song_count = result.get("songCount", 0)
        return {
            "songs": self._parse_songs(songs_raw),
            "total": song_count
        }

    async def get_user_playlists(self) -> list:
        """获取当前登录用户的歌单"""
        from pyncm.apis.login import GetCurrentLoginStatus
        from pyncm.apis.user import GetUserPlaylists

        status = await self._run_sync(GetCurrentLoginStatus)
        if status.get("code") != 200 or not status.get("profile"):
            return []

        user_id = status["profile"]["userId"]
        data = await self._run_sync(GetUserPlaylists, user_id)
        if data.get("code") != 200:
            return []

        playlists = data.get("playlist", [])
        result = []
        for p in playlists:
            result.append({
                "id": p["id"],
                "name": p.get("name", "未命名歌单"),
                "cover": p.get("coverImgUrl", ""),
                "track_count": p.get("trackCount", 0),
                "description": p.get("description", "") or ""
            })
        return result

    async def get_playlist_tracks(self, playlist_id: int, limit: int = 20, offset: int = 0) -> list:
        """获取歌单中的部分歌曲（支持分页并缓存歌单 trackIds）"""
        from pyncm.apis.playlist import GetPlaylistInfo
        from pyncm.apis.track import GetTrackDetail

        now = time.monotonic()
        cached = self._playlist_cache.get(playlist_id)
        if cached and (now - cached[0]) < self._PLAYLIST_CACHE_TTL:
            track_ids = cached[1]
        else:
            data = await self._run_sync(GetPlaylistInfo, playlist_id)
            raw_ids = data.get("playlist", {}).get("trackIds", [])
            track_ids = [t["id"] for t in raw_ids if isinstance(t, dict) and "id" in t]
            self._playlist_cache[playlist_id] = (now, track_ids)

        batch_ids = track_ids[offset:offset + limit]
        if not batch_ids:
            return []

        detail = await self._run_sync(GetTrackDetail, batch_ids)
        return self._parse_songs(detail.get("songs", []))

    async def get_song_urls(self, song_ids: list[int]) -> dict[int, str]:
        """批量获取歌曲播放链接，返回 {song_id: url} 映射"""
        from pyncm.apis.track import GetTrackAudio
        if not song_ids:
            return {}

        url_map: dict[int, str] = {}
        chunk_size = 50
        for i in range(0, len(song_ids), chunk_size):
            chunk = song_ids[i:i + chunk_size]
            try:
                data = await self._run_sync(GetTrackAudio, chunk)
                for item in data.get("data", []):
                    sid = item.get("id")
                    u = item.get("url")
                    if sid is not None and u:
                        url_map[int(sid)] = u
            except Exception as e:
                logger.warning(f"批量获取歌曲播放链接失败 ({chunk}): {e}")
        return url_map

    async def get_song_url(self, song_id: int) -> str | None:
        urls = await self.get_song_urls([song_id])
        return urls.get(int(song_id))

    async def download_bytes(self, url: str) -> bytes | None:
        """使用复用连接池下载二进制内容（封面图等）"""
        try:
            client = self._get_http_client()
            resp = await client.get(url, timeout=30.0)
            if resp.status_code == 200 and resp.content:
                return resp.content
        except Exception as e:
            logger.warning(f"下载资源失败 ({url}): {e}")
        return None

    @staticmethod
    def _detect_audio_ext(url: str, content_type: str) -> str:
        ext = Path(urlsplit(url).path).suffix.lower()
        if ext in _VALID_AUDIO_EXTS:
            return ext
        ct = content_type.lower()
        if "flac" in ct:
            return ".flac"
        if "mp4" in ct or "m4a" in ct or "aac" in ct:
            return ".m4a"
        if "ogg" in ct:
            return ".ogg"
        return ".mp3"

    async def download_song(self, song_id: int, song_name: str, save_dir: str, url: str | None = None) -> str | None:
        if not url:
            url = await self.get_song_url(song_id)
        if not url:
            return None

        save_dir_path = Path(save_dir)
        save_dir_path.mkdir(parents=True, exist_ok=True)
        tmp_path: Path | None = None
        try:
            client = self._get_http_client()
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    return None
                content_type = (resp.headers.get("content-type") or "").lower()
                if content_type.startswith("text/") or "html" in content_type or "json" in content_type:
                    logger.warning(f"音频链接返回非音频内容 ({song_name}, Content-Type: {content_type})")
                    return None

                ext = self._detect_audio_ext(url, content_type)
                save_path = save_dir_path / f"{song_id}{ext}"
                tmp_path = save_dir_path / f"{song_id}{ext}.tmp"

                total_bytes = 0
                head_bytes = b""
                with open(tmp_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        if not head_bytes:
                            head_bytes = chunk[:64].lstrip().lower()
                            if head_bytes.startswith(b"<html") or head_bytes.startswith(b"<!doctype") or head_bytes.startswith(b"{"):
                                logger.warning(f"下载到无效音频内容 ({song_name}, ID: {song_id})")
                                raise ValueError("Invalid audio header")
                        f.write(chunk)
                        total_bytes += len(chunk)

                if total_bytes < 10000:
                    if tmp_path.exists():
                        tmp_path.unlink()
                    return None

                tmp_path.replace(save_path)
                return str(save_path)
        except Exception as e:
            logger.warning(f"下载音频异常 ({song_name}, ID: {song_id}): {e}")
            if tmp_path is not None:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except Exception:
                    pass
            return None

    async def get_lyrics(self, song_id: int) -> str:
        try:
            from pyncm.apis.track import GetTrackLyrics
            data = await self._run_sync(GetTrackLyrics, song_id)
            return data.get("lrc", {}).get("lyric", "")
        except Exception:
            return ""

    @staticmethod
    def _parse_songs(songs_raw: list) -> list:
        result = []
        for song in songs_raw or []:
            if not isinstance(song, dict) or "id" not in song:
                continue
            ar = song.get("ar", song.get("artists", []))
            al = song.get("al", song.get("album", {}))
            album_name = al.get("name", "") if isinstance(al, dict) else ""
            album_pic = al.get("picUrl", "") if isinstance(al, dict) else ""
            artists = [a.get("name", "") for a in (ar or []) if isinstance(a, dict) and a.get("name")]
            result.append({
                "id": song["id"],
                "name": song.get("name") or "未知歌曲",
                "artists": artists,
                "album": album_name,
                "album_pic": album_pic,
                "duration_ms": song.get("dt", song.get("duration", 0)) or 0,
            })
        return result
