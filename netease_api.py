# -*- coding: utf-8 -*-
"""网易云音乐 API 客户端 - 使用 pyncm 加密"""
import asyncio
import logging
from pathlib import Path
from functools import partial

logger = logging.getLogger('pipeline.netease_api')

# ── 用 pyncm 装饰器定义每日推荐接口 ──
from pyncm.apis import WeapiCryptoRequest

@WeapiCryptoRequest
def _GetDailyRecommendSongs():
    """获取每日推荐歌曲"""
    return "/weapi/v3/discovery/recommend/songs", {}


def _init_pyncm(cookie: str = ""):
    from pyncm import GetCurrentSession
    if cookie:
        session = GetCurrentSession()
        session.cookies.set("MUSIC_U", cookie, domain=".music.163.com")


class NeteaseAPI:
    def __init__(self, cookie: str = ""):
        self.cookie = cookie
        _init_pyncm(cookie)

    async def _run_sync(self, func, *args, **kwargs):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

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
                "name": p["name"],
                "cover": p.get("coverImgUrl", ""),
                "track_count": p.get("trackCount", 0),
                "description": p.get("description", "") or ""
            })
        return result

    async def get_playlist_tracks(self, playlist_id: int, limit: int = 20, offset: int = 0) -> list:
        """获取歌单中的部分歌曲（支持分页）"""
        from pyncm.apis.playlist import GetPlaylistAllTracks
        data = await self._run_sync(GetPlaylistAllTracks, playlist_id, limit=limit, offset=offset)
        songs = data.get("songs", [])
        return self._parse_songs(songs)

    async def get_song_url(self, song_id: int) -> str | None:
        from pyncm.apis.track import GetTrackAudio
        try:
            data = await self._run_sync(GetTrackAudio, [song_id])
            items = data.get("data", [])
            if items and items[0].get("url"):
                return items[0]["url"]
        except Exception:
            pass
        return None

    async def download_song(self, song_id: int, song_name: str, save_dir: str) -> str | None:
        url = await self.get_song_url(song_id)
        if not url:
            return None
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / f"{song_id}.mp3"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code != 200 or len(resp.content) < 10000:
                    return None
                save_path.write_bytes(resp.content)
                return str(save_path)
        except Exception:
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
        for song in songs_raw:
            ar = song.get("ar", song.get("artists", []))
            al = song.get("al", song.get("album", {}))
            album_name = al.get("name", "") if isinstance(al, dict) else ""
            album_pic = al.get("picUrl", "") if isinstance(al, dict) else ""
            result.append({
                "id": song["id"],
                "name": song["name"],
                "artists": [a["name"] for a in ar] if ar else [],
                "album": album_name,
                "album_pic": album_pic,
                "duration_ms": song.get("dt", song.get("duration", 0)),
            })
        return result
