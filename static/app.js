const API_BASE = window.location.origin;
const DEFAULT_COVER = 'https://p1.music.126.net/rlLj3MMgn6WZTQgzRZOOrg==/109951164420512035.jpg';

let allSongs = [];
let selectedSongs = [];
let allPlaylists = [];
let activePlaylistId = 'daily_recommend';

let currentPage = 0;
let totalCount = 0;
const pageSize = 20;
let paginationMode = 'recommend'; // 'search' | 'playlist' | 'recommend'
let currentSearchQuery = '';
let searchCache = {};

let tags = ['音乐', '网易云音乐'];
let formatTags = ['音乐', '网易云音乐'];
let currentFormats = [];

let latestTasks = [];
let selectedTaskId = null;
let pollInterval = null;
let isStatusPolling = false;
let lastSidebarTasksKey = '';
let lastMonitorTasksKey = '';
let lastConsoleLogsKey = '';

let neteaseLoginPolling = null;
let isNeteaseChecking = false;
let loginPolling = null;
let isBilibiliChecking = false;

let currentPlayingSongId = null;
let globalAudio = null;
let playerBar = null;
let dragSrcId = null;

let completedTaskIds = new Set();
try {
    const savedShown = sessionStorage.getItem('music_pipeline_shown_completed_tasks');
    if (savedShown) {
        completedTaskIds = new Set(JSON.parse(savedShown));
    }
} catch (e) {}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function formatDuration(ms) {
    if (!ms || Number.isNaN(ms)) return '--:--';
    const totalSeconds = Math.floor(ms / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
}

function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.style.position = 'fixed';
    toast.style.bottom = '110px';
    toast.style.right = '40px';
    toast.style.zIndex = '9999';
    toast.style.padding = '12px 24px';
    toast.style.borderRadius = '12px';
    toast.style.fontSize = '13px';
    toast.style.fontWeight = '600';
    toast.style.boxShadow = '0 8px 30px rgba(0,0,0,0.5)';
    toast.style.backdropFilter = 'blur(15px)';
    toast.style.transition = 'all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275)';
    toast.style.transform = 'translateY(50px) scale(0.8)';
    toast.style.opacity = '0';

    if (type === 'success') {
        toast.style.background = 'rgba(46, 204, 113, 0.15)';
        toast.style.border = '1px solid rgba(46, 204, 113, 0.4)';
        toast.style.color = '#2ecc71';
    } else {
        toast.style.background = 'rgba(255, 71, 87, 0.15)';
        toast.style.border = '1px solid rgba(255, 71, 87, 0.4)';
        toast.style.color = '#ff4757';
    }

    toast.innerText = message;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.transform = 'translateY(0) scale(1)';
        toast.style.opacity = '1';
    }, 50);

    setTimeout(() => {
        toast.style.transform = 'translateY(-20px) scale(0.9)';
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 400);
    }, 3000);
}

/* ========== SPA 页面切换 ========== */
function updateSynthesisSubtitle() {
    const subtitle = document.getElementById('page-subtitle');
    if (!subtitle) return;
    if (paginationMode === 'search') {
        subtitle.innerText = `🔍 搜索结果: "${currentSearchQuery}"`;
    } else if (paginationMode === 'playlist') {
        const playlist = allPlaylists.find(p => String(p.id) === String(activePlaylistId));
        subtitle.innerText = playlist ? `📂 歌单: "${playlist.name}"` : '📂 歌单曲目';
    } else {
        subtitle.innerText = '今日推荐';
    }
}

function switchPage(page) {
    const pages = ['synthesis', 'monitor', 'upload'];
    pages.forEach(p => {
        const btn = document.getElementById(`nav-link-${p}`);
        const panel = document.getElementById(`panel-${p}`);
        if (btn) {
            if (p === page) {
                btn.classList.add('active');
                btn.style.background = 'rgba(0, 242, 254, 0.15)';
                btn.style.color = 'var(--accent)';
            } else {
                btn.classList.remove('active');
                btn.style.background = 'transparent';
                btn.style.color = 'var(--text-dim)';
            }
        }
        if (panel) {
            panel.style.display = (p === page) ? 'flex' : 'none';
        }
    });

    document.querySelectorAll('.synthesis-only').forEach(el => {
        const isMonitorAlso = el.classList.contains('monitor-only');
        el.style.display = (page === 'synthesis' || (page === 'monitor' && isMonitorAlso)) ? '' : 'none';
    });
    document.querySelectorAll('.monitor-only').forEach(el => {
        const isSynthesisAlso = el.classList.contains('synthesis-only');
        if (!isSynthesisAlso) {
            el.style.display = (page === 'monitor') ? '' : 'none';
        }
    });
    document.querySelectorAll('.upload-only').forEach(el => {
        el.style.display = (page === 'upload') ? '' : 'none';
    });

    const subtitle = document.getElementById('page-subtitle');
    const searchContainer = document.getElementById('search-container');
    if (page === 'synthesis') {
        updateSynthesisSubtitle();
        if (searchContainer) searchContainer.style.display = 'flex';
    } else if (page === 'monitor') {
        if (subtitle) subtitle.innerText = '任务监控流水线';
        if (searchContainer) searchContainer.style.display = 'none';
    } else if (page === 'upload') {
        if (subtitle) subtitle.innerText = 'B站视频上传投稿';
        if (searchContainer) searchContainer.style.display = 'none';
        const activeSubtab = sessionStorage.getItem('music_pipeline_active_upload_subtab') || 'upload';
        switchUploadSubTab(activeSubtab);
    }

    sessionStorage.setItem('music_pipeline_active_page', page);
}

function switchUploadSubTab(subtab) {
    document.querySelectorAll('#panel-upload .tab-btn, .upload-only .tab-btn').forEach(btn => {
        btn.classList.remove('active');
        btn.style.background = 'transparent';
        btn.style.color = 'var(--text-dim)';
        btn.style.border = 'none';
    });
    const activeBtn = document.getElementById(`subtab-btn-${subtab}`);
    if (activeBtn) {
        activeBtn.classList.add('active');
        activeBtn.style.background = 'rgba(255,255,255,0.05)';
        activeBtn.style.color = 'var(--accent)';
        activeBtn.style.border = '1px solid var(--glass-border)';
    }
    document.getElementById('tab-upload').style.display = (subtab === 'upload') ? 'block' : 'none';
    document.getElementById('tab-formats').style.display = (subtab === 'formats') ? 'block' : 'none';

    if (subtab === 'formats') {
        loadFormats();
    }
    sessionStorage.setItem('music_pipeline_active_upload_subtab', subtab);
}

/* ========== 会话缓存与歌单加载 ========== */
function saveSessionCache() {
    try {
        sessionStorage.setItem('music_pipeline_all_songs', JSON.stringify(allSongs));
        sessionStorage.setItem('music_pipeline_active_playlist_id', activePlaylistId);
        sessionStorage.setItem('music_pipeline_pagination_mode', paginationMode);
        sessionStorage.setItem('music_pipeline_current_page', String(currentPage));
        sessionStorage.setItem('music_pipeline_total_count', String(totalCount));
        sessionStorage.setItem('music_pipeline_search_query', currentSearchQuery);
    } catch (e) {}
}

function forceRefreshSongs() {
    [
        'music_pipeline_all_songs',
        'music_pipeline_active_playlist_id',
        'music_pipeline_pagination_mode',
        'music_pipeline_current_page',
        'music_pipeline_total_count',
        'music_pipeline_search_query'
    ].forEach(k => sessionStorage.removeItem(k));

    searchCache = {};

    if (paginationMode === 'search') {
        executeSearch(true);
    } else if (paginationMode === 'playlist') {
        selectPlaylist(activePlaylistId, true);
    } else {
        fetchSongs();
    }
}

async function fetchPlaylists() {
    const container = document.getElementById('playlists-container');
    if (!container) return;
    try {
        const res = await fetch(`${API_BASE}/netease/playlists`);
        if (!res.ok) throw new Error();
        const data = await res.json();
        allPlaylists = data.playlists || [];
        renderPlaylists();
        if (sessionStorage.getItem('music_pipeline_active_page') === 'synthesis' || paginationMode === 'playlist') {
            updateSynthesisSubtitle();
        }
    } catch (e) {
        container.innerHTML = `
            <div style="text-align: center; padding: 20px; color: var(--text-dim); font-size: 13px;">
                同步歌单失败，请重新登录
            </div>
        `;
    }
}

function renderPlaylists() {
    const container = document.getElementById('playlists-container');
    if (!container) return;

    let html = `
        <div class="playlist-item daily ${activePlaylistId === 'daily_recommend' ? 'active' : ''}" data-playlist-id="daily_recommend">
            <div style="font-size: 18px; width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; background: rgba(0, 242, 254, 0.1); border-radius: 6px;">📅</div>
            <div class="info">
                <div class="name">每日推荐歌曲</div>
                <div class="count">网易云每日新歌推荐</div>
            </div>
        </div>
    `;

    if (allPlaylists.length > 0) {
        html += allPlaylists.map(p => {
            const isActive = String(activePlaylistId) === String(p.id);
            const coverUrl = escapeHtml(p.cover || DEFAULT_COVER);
            return `
                <div class="playlist-item ${isActive ? 'active' : ''}" data-playlist-id="${escapeHtml(p.id)}">
                    <img src="${coverUrl}" alt="cover" onerror="this.src='${DEFAULT_COVER}'">
                    <div class="info">
                        <div class="name">${escapeHtml(p.name)}</div>
                        <div class="count">${Number(p.track_count) || 0} 首歌曲</div>
                    </div>
                </div>
            `;
        }).join('');
    }
    container.innerHTML = html;
}

async function selectPlaylist(id, keepPage = false) {
    activePlaylistId = id;
    renderPlaylists();
    renderSkeletonSongs();

    document.getElementById('search-input').value = '';
    document.getElementById('search-btn').style.display = 'none';
    document.getElementById('clear-search-btn').style.display = 'none';

    if (id === 'daily_recommend') {
        paginationMode = 'recommend';
        currentPage = 0;
        totalCount = 0;
        const pc = document.getElementById('pagination-controls');
        if (pc) pc.style.display = 'none';
        updateSynthesisSubtitle();
        document.getElementById('status-display').innerText = '正在获取每日推荐...';
        await fetchSongs();
    } else {
        paginationMode = 'playlist';
        if (!keepPage) currentPage = 0;
        const playlist = allPlaylists.find(p => String(p.id) === String(id));
        totalCount = playlist ? playlist.track_count : 0;

        updateSynthesisSubtitle();
        document.getElementById('status-display').innerText = '正在加载歌单曲目...';

        try {
            const offset = currentPage * pageSize;
            const res = await fetch(`${API_BASE}/netease/playlist/tracks?id=${encodeURIComponent(id)}&limit=${pageSize}&offset=${offset}`);
            if (!res.ok) throw new Error();
            const data = await res.json();
            allSongs = data.songs || [];

            updateActionBar();
            renderSongs();
            document.getElementById('status-display').innerText = `已加载第 ${offset + 1} - ${offset + allSongs.length} 首，共计 ${totalCount} 首`;

            updatePaginationControls();
            saveSessionCache();
        } catch (e) {
            document.getElementById('status-display').innerText = '加载歌单歌曲失败';
            document.getElementById('songs-grid').innerHTML = `
                <div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--text-dim);">
                    无法读取此歌单曲目或连接超时
                </div>
            `;
            const pc = document.getElementById('pagination-controls');
            if (pc) pc.style.display = 'none';
        }
    }
}

async function fetchSongs() {
    document.getElementById('status-display').innerText = '加载中...';
    try {
        const res = await fetch(`${API_BASE}/recommendations`);
        if (!res.ok) {
            const data = await res.json();
            document.getElementById('status-display').innerText = '加载失败: ' + (data.detail || '请先登录或刷新Cookie');
            return;
        }
        const data = await res.json();
        allSongs = data.songs || [];
        updateActionBar();
        renderSongs();
        document.getElementById('status-display').innerText = `已加载 ${allSongs.length} 首推荐`;
        saveSessionCache();
    } catch (e) {
        document.getElementById('status-display').innerText = '加载失败，请检查网络或登录状态';
    }
}

async function loadUploadFormats() {
    try {
        const res = await fetch(`${API_BASE}/bilibili/upload-formats`);
        if (!res.ok) return;
        const formats = await res.json();
        const select = document.getElementById('upload-format');
        if (select && Array.isArray(formats) && formats.length > 0) {
            select.innerHTML = formats.map(f => `<option value="${escapeHtml(f.name)}">${escapeHtml(f.name)}</option>`).join('');
        }
    } catch (e) {}
}

/* ========== 歌曲网格与选曲队列（无内联字符串转义隐患 & 增量更新） ========== */
function renderSongs() {
    const grid = document.getElementById('songs-grid');
    if (allSongs.length === 0) {
        grid.innerHTML = `
            <div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--text-dim);">
                暂无曲目，请确认配置或重新检索
            </div>
        `;
        return;
    }

    grid.innerHTML = allSongs.map(s => {
        const idx = selectedSongs.findIndex(item => item.id === s.id);
        const isCurPlaying = currentPlayingSongId === s.id && globalAudio && !globalAudio.paused;
        const safeName = escapeHtml(s.name);
        const safeArtists = escapeHtml((s.artists || []).join(', '));
        const safeCover = escapeHtml(s.album_pic || DEFAULT_COVER);
        return `
            <div class="song-card ${idx !== -1 ? 'selected' : ''} ${isCurPlaying ? 'playing' : ''}" data-id="${s.id}">
                <div class="badge">${idx !== -1 ? idx + 1 : 0}</div>
                <div class="cover-wrap">
                    <img class="cover-art" src="${safeCover}" alt="${safeName}" onerror="this.src='${DEFAULT_COVER}'">
                    <div class="play-btn" data-play-id="${s.id}">
                        <svg class="play-icon" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" style="${isCurPlaying ? 'display:none;' : 'display:block;'}"><path d="M8 5v14l11-7z"/></svg>
                        <svg class="pause-icon" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" style="${isCurPlaying ? 'display:block;' : 'display:none;'}"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
                    </div>
                    <div class="audio-wave-anim" style="${isCurPlaying ? 'display:flex;' : 'display:none;'}">
                        <div class="wave-bar bar-1"></div>
                        <div class="wave-bar bar-2"></div>
                        <div class="wave-bar bar-3"></div>
                    </div>
                </div>
                <div class="song-info">
                    <div class="name" title="${safeName}">${safeName}</div>
                    <div class="artist" title="${safeArtists}">${safeArtists}</div>
                </div>
            </div>
        `;
    }).join('');
}

function syncSongCardsSelection() {
    const selectedIndexMap = new Map();
    selectedSongs.forEach((s, i) => selectedIndexMap.set(String(s.id), i + 1));

    document.querySelectorAll('#songs-grid .song-card').forEach(card => {
        const id = card.getAttribute('data-id');
        const order = selectedIndexMap.get(String(id));
        const badge = card.querySelector('.badge');
        if (order !== undefined) {
            card.classList.add('selected');
            if (badge) badge.textContent = String(order);
        } else {
            card.classList.remove('selected');
            if (badge) badge.textContent = '0';
        }
    });
}

function toggleSong(id) {
    const idx = selectedSongs.findIndex(s => s.id === id);
    if (idx !== -1) {
        selectedSongs.splice(idx, 1);
    } else {
        const song = allSongs.find(s => s.id === id);
        if (song) selectedSongs.push(song);
    }
    updateActionBar();
    syncSongCardsSelection();
}

function removeSongFromQueue(id) {
    const idx = selectedSongs.findIndex(s => s.id === id);
    if (idx !== -1) {
        selectedSongs.splice(idx, 1);
        updateActionBar();
        syncSongCardsSelection();
    }
}

function selectAll() {
    allSongs.forEach(s => {
        if (!selectedSongs.some(item => item.id === s.id)) {
            selectedSongs.push(s);
        }
    });
    updateActionBar();
    syncSongCardsSelection();
}

function deselectAll() {
    selectedSongs = [];
    updateActionBar();
    syncSongCardsSelection();
}

function updateActionBar() {
    const bar = document.getElementById('action-bar');
    const count = document.getElementById('select-count');
    const queueDiv = document.getElementById('selection-queue');
    const paginationControls = document.getElementById('pagination-controls');

    if (count) count.innerText = String(selectedSongs.length);

    if (selectedSongs.length > 0) {
        if (bar) bar.classList.add('visible');
        if (paginationControls) paginationControls.style.marginBottom = '200px';

        if (queueDiv) {
            queueDiv.innerHTML = selectedSongs.map((song, index) => `
                <div class="queue-item" draggable="true" data-id="${song.id}">
                    <img src="${escapeHtml(song.album_pic || DEFAULT_COVER)}" alt="cover">
                    <div class="queue-index">${index + 1}</div>
                    <div class="queue-remove-btn" data-remove-id="${song.id}">×</div>
                </div>
            `).join('');
        }
    } else {
        if (bar) bar.classList.remove('visible');
        if (queueDiv) queueDiv.innerHTML = '';
        if (paginationControls) paginationControls.style.marginBottom = '90px';
    }

    try {
        sessionStorage.setItem('music_pipeline_selected_songs', JSON.stringify(selectedSongs));
    } catch (e) {}
}

/* ========== 合成提交与状态轮询 ========== */
async function startGenerate() {
    if (selectedSongs.length === 0) return;
    const autoUpload = document.getElementById('auto-upload').checked;
    const formatName = autoUpload ? document.getElementById('upload-format').value : '';

    try {
        const res = await fetch(`${API_BASE}/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                songs: selectedSongs,
                combine: true,
                auto_upload: autoUpload,
                upload_format_name: formatName
            })
        });

        if (res.ok) {
            showToast('合成任务已成功加入后台排队！');
            deselectAll();
            setTimeout(checkQueueOnce, 300);
        } else {
            const err = await res.json();
            showToast('启动合成失败: ' + (err.detail || '未知错误'), 'error');
        }
    } catch (e) {
        showToast('请求服务失败，请检查网络', 'error');
    }
}

function getStatusBadgeMeta(status) {
    switch (status) {
        case 'waiting':
            return { color: 'var(--info)', bg: 'rgba(0, 242, 254, 0.1)', cls: 'status-waiting', text: '排队中' };
        case 'running':
            return { color: 'var(--accent)', bg: 'rgba(0, 242, 254, 0.15)', cls: 'status-running', text: '合成中' };
        case 'completed':
            return { color: 'var(--success)', bg: 'rgba(46, 204, 113, 0.1)', cls: 'status-completed', text: '已完成' };
        case 'cancelled':
            return { color: '#ff9f43', bg: 'rgba(255, 159, 67, 0.1)', cls: 'status-cancelled', text: '已取消' };
        case 'failed':
            return { color: 'var(--error)', bg: 'rgba(255, 71, 87, 0.1)', cls: 'status-failed', text: '失败' };
        default:
            return { color: 'var(--text-dim)', bg: 'rgba(255,255,255,0.05)', cls: '', text: status || '等待中' };
    }
}

function renderTaskQueue(tasks) {
    const container = document.getElementById('task-queue-card');
    if (!container) return;

    const snapshotKey = JSON.stringify((tasks || []).map(t => [t.id, t.status, t.progress, t.current_status_text, t.songs_count]));
    if (snapshotKey === lastSidebarTasksKey) return;
    lastSidebarTasksKey = snapshotKey;

    if (!tasks || tasks.length === 0) {
        container.innerHTML = `
            <div style="text-align: center; color: var(--text-dim); font-size: 13px; padding: 10px 0;">
                暂无合成任务
            </div>
        `;
        return;
    }

    container.innerHTML = tasks.map(task => {
        const meta = getStatusBadgeMeta(task.status);
        const safeId = escapeHtml(task.id);
        const actionBtn = (task.status === 'waiting' || task.status === 'running')
            ? `<button data-task-action="cancel" data-task-id="${safeId}" style="background: rgba(255,71,87,0.1); border: 1px solid rgba(255,71,87,0.3); color: var(--error); padding: 4px 10px; font-size: 11px; border-radius: 12px; cursor: pointer; font-weight: bold;">取消</button>`
            : `<button data-task-action="delete" data-task-id="${safeId}" style="background: rgba(255,255,255,0.03); border: 1px solid var(--glass-border); color: var(--text-dim); padding: 4px 10px; font-size: 11px; border-radius: 12px; cursor: pointer;">删除</button>`;

        const progressPct = task.progress || 0;
        const showProgress = (task.status === 'running' || task.status === 'waiting' || task.status === 'completed');

        return `
            <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--glass-border); border-radius: 10px; padding: 10px; display: flex; flex-direction: column; gap: 8px; text-align: left;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-size: 12px; font-weight: 700; color: var(--text-main); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 145px;" title="${escapeHtml((task.songs_names || []).join(', '))}">
                        任务 #${safeId} (${task.songs_count}首)
                    </span>
                    <span style="background: ${meta.bg}; color: ${meta.color}; font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 20px;">
                        ${meta.text}
                    </span>
                </div>
                <div style="font-size: 11px; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                    ${escapeHtml(task.current_status_text)}
                </div>
                ${showProgress ? `
                <div style="display: flex; align-items: center; gap: 8px;">
                    <div style="flex: 1; height: 4px; background: rgba(255,255,255,0.05); border-radius: 2px; overflow: hidden;">
                        <div style="width: ${progressPct}%; height: 100%; background: var(--accent-gradient); transition: width 0.3s;"></div>
                    </div>
                    <span style="font-size: 10px; font-weight: 800; color: var(--text-dim); min-width: 24px; text-align: right;">${progressPct}%</span>
                </div>` : ''}
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 2px; font-size: 10px; color: var(--text-dim);">
                    <span>创建于: ${escapeHtml(task.created_at)}</span>
                    ${actionBtn}
                </div>
            </div>
        `;
    }).join('');
}

function renderMonitorTaskCards(tasks) {
    const container = document.getElementById('logs-task-container');
    if (!container) return;

    const snapshotKey = JSON.stringify([selectedTaskId, (tasks || []).map(t => [t.id, t.status, t.progress, t.current_status_text, t.songs_count])]);
    if (snapshotKey === lastMonitorTasksKey) return;
    lastMonitorTasksKey = snapshotKey;

    container.innerHTML = tasks.map(task => {
        const isSelected = task.id === selectedTaskId;
        const meta = getStatusBadgeMeta(task.status);
        const safeId = escapeHtml(task.id);
        const actionBtn = (task.status === 'waiting' || task.status === 'running')
            ? `<button data-task-action="cancel" data-task-id="${safeId}" style="background: rgba(255,71,87,0.1); border: 1px solid rgba(255,71,87,0.3); color: var(--error); padding: 4px 12px; font-size: 12px; border-radius: 20px; font-weight: bold; cursor: pointer;">取消</button>`
            : `<button data-task-action="delete" data-task-id="${safeId}" style="background: rgba(255,255,255,0.03); border: 1px solid var(--glass-border); color: var(--text-dim); padding: 4px 12px; font-size: 12px; border-radius: 20px; cursor: pointer;">删除</button>`;

        const progressPct = task.progress || 0;
        const showProgress = (task.status === 'running' || task.status === 'waiting' || task.status === 'completed');

        return `
            <div class="task-card ${isSelected ? 'selected' : ''}" data-task-select="${safeId}">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div style="display: flex; flex-direction: column; gap: 4px; overflow: hidden; flex: 1; padding-right: 15px;">
                        <div style="font-size: 15px; font-weight: 800; color: var(--text-main); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                            任务 #${safeId} (${task.songs_count}首歌曲)
                        </div>
                        <div style="font-size: 12px; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${escapeHtml((task.songs_names || []).join('、'))}">
                            曲目清单: ${escapeHtml((task.songs_names || []).join('、'))}
                        </div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 12px; flex-shrink: 0;">
                        <span class="status-badge ${meta.cls}">${meta.text}</span>
                        ${actionBtn}
                    </div>
                </div>
                <div style="font-size: 13px; color: var(--text-main); font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                    📢 状态: ${escapeHtml(task.current_status_text)}
                </div>
                ${showProgress ? `
                <div style="display: flex; align-items: center; gap: 12px; margin-top: 2px;">
                    <div style="flex: 1; height: 6px; background: rgba(255,255,255,0.05); border-radius: 3px; overflow: hidden;">
                        <div style="width: ${progressPct}%; height: 100%; background: var(--accent-gradient); transition: width 0.3s;"></div>
                    </div>
                    <span style="font-size: 13px; font-weight: 800; color: var(--accent); min-width: 36px; text-align: right;">${progressPct}%</span>
                </div>` : ''}
                <div style="font-size: 11px; color: var(--text-dim); text-align: right; margin-top: -4px;">
                    创建于: ${escapeHtml(task.created_at)}
                </div>
            </div>
        `;
    }).join('');
}

function renderMonitorPanel(tasks) {
    const container = document.getElementById('logs-task-container');
    const consoleCard = document.getElementById('console-card');
    if (!container || !consoleCard || !tasks) return;

    if (tasks.length === 0) {
        if (lastMonitorTasksKey !== 'EMPTY') {
            lastMonitorTasksKey = 'EMPTY';
            lastConsoleLogsKey = '';
            container.innerHTML = `
                <div class="status-idle">
                    <div style="font-size: 40px;">🛌</div>
                    <h3 style="font-size: 20px; font-weight: 700; color: var(--text-main);">当前没有正在运行的制作任务</h3>
                    <p style="font-size: 14px; max-width: 400px; line-height: 1.6;">流水线当前处于空闲状态。请在合成页挑选歌曲并一键开始生成视频。</p>
                </div>
            `;
        }
        consoleCard.style.display = 'none';
        selectedTaskId = null;
        return;
    }

    if (!selectedTaskId || !tasks.some(t => t.id === selectedTaskId)) {
        const runningTask = tasks.find(t => t.status === 'running') || tasks[0];
        selectedTaskId = runningTask ? runningTask.id : null;
    }

    renderMonitorTaskCards(tasks);

    const task = tasks.find(t => t.id === selectedTaskId);
    if (task) {
        consoleCard.style.display = 'flex';
        const consoleDiv = document.getElementById('console');
        const logs = task.logs || [];
        const logsKey = `${task.id}::${logs.length}::${logs[logs.length - 1] || ''}`;
        if (logsKey !== lastConsoleLogsKey) {
            const nearBottom = (consoleDiv.scrollHeight - consoleDiv.scrollTop - consoleDiv.clientHeight) < 40;
            lastConsoleLogsKey = logsKey;
            if (logs.length > 0) {
                consoleDiv.innerHTML = logs.map(l => `<div>&gt; ${escapeHtml(l)}</div>`).join('');
            } else {
                consoleDiv.innerHTML = `<div>&gt; 等待任务启动以输出底层压制日志...</div>`;
            }
            if (nearBottom || logs.length <= 2) {
                consoleDiv.scrollTop = consoleDiv.scrollHeight;
            }
        }
    } else {
        consoleCard.style.display = 'none';
    }
}

function selectTask(id) {
    selectedTaskId = id;
    lastMonitorTasksKey = '';
    lastConsoleLogsKey = '';
    renderMonitorPanel(latestTasks);
}

async function cancelTask(id) {
    if (!confirm('确定要取消此合成任务吗？')) return;
    try {
        const res = await fetch(`${API_BASE}/tasks/${encodeURIComponent(id)}/cancel`, { method: 'POST' });
        if (res.ok) {
            showToast('合成任务取消指令已成功下发！');
            checkQueueOnce();
        } else {
            showToast('取消失败，请刷新重试', 'error');
        }
    } catch (e) {
        showToast('连接失败，请检查网络', 'error');
    }
}

async function deleteTask(id) {
    if (!confirm('确定要删除此任务记录吗？')) return;
    try {
        const res = await fetch(`${API_BASE}/tasks/${encodeURIComponent(id)}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('任务记录已成功清除！');
            if (selectedTaskId === id) selectedTaskId = null;
            checkQueueOnce();
        } else {
            showToast('删除失败，请刷新重试', 'error');
        }
    } catch (e) {
        showToast('连接失败，请检查网络', 'error');
    }
}

function handleTaskCompletions(tasks) {
    if (!tasks || tasks.length === 0) return;
    tasks.forEach(task => {
        if (task.status === 'completed' && !completedTaskIds.has(task.id)) {
            completedTaskIds.add(task.id);
            try {
                sessionStorage.setItem('music_pipeline_shown_completed_tasks', JSON.stringify(Array.from(completedTaskIds)));
            } catch (e) {}
            showToast(`任务 #${task.id} 视频合成已全部完成！`);
            showCompletionModalForTask(task);
        } else if (task.status === 'failed' && !completedTaskIds.has(task.id)) {
            completedTaskIds.add(task.id);
            try {
                sessionStorage.setItem('music_pipeline_shown_completed_tasks', JSON.stringify(Array.from(completedTaskIds)));
            } catch (e) {}
            showToast(`任务 #${task.id} 视频合成不幸失败！`, 'error');
        }
    });
}

async function checkQueueOnce() {
    if (isStatusPolling) return;
    isStatusPolling = true;
    try {
        const res = await fetch(`${API_BASE}/status`);
        if (!res.ok) return;
        const data = await res.json();
        latestTasks = data.tasks || [];
        renderTaskQueue(latestTasks);
        renderMonitorPanel(latestTasks);
        handleTaskCompletions(latestTasks);
    } catch (e) {
        console.error('轮询状态失败', e);
    } finally {
        isStatusPolling = false;
    }
}

function startStatusPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(checkQueueOnce, 1500);
}

function showCompletionModalForTask(task) {
    const openUploadBtn = document.getElementById('open-upload-btn');
    const copyPathBtn = document.getElementById('copy-path-btn');
    const videoPathEl = document.getElementById('modal-video-path');
    const uploadInfoEl = document.getElementById('upload-info');

    // 每次弹窗先重置按钮可见状态，避免跨任务污染
    if (openUploadBtn) openUploadBtn.style.display = 'none';
    if (copyPathBtn) copyPathBtn.style.display = 'inline-block';

    if (!task.combine || !task.final_video_path) {
        if (videoPathEl) videoPathEl.innerText = '已生成独立单曲片段（未启用视频拼接）';
        if (copyPathBtn) copyPathBtn.style.display = 'none';
        if (uploadInfoEl) uploadInfoEl.innerText = '可在输出目录查看生成的单曲片段。';
        document.getElementById('completion-modal').style.display = 'flex';
        return;
    }

    if (videoPathEl) videoPathEl.innerText = task.final_video_path;

    const hasUpload = task.upload_status === 'success' || (task.logs && task.logs.some(l => l.includes('Upload success')));
    const uploadFailed = task.upload_status === 'failed' || (task.logs && task.logs.some(l => l.includes('Upload failed') || l.includes('Auto-upload error')));

    if (task.auto_upload) {
        if (hasUpload) {
            uploadInfoEl.innerHTML = '<span style="color:#2ecc71;">已自动上传到B站！</span>';
        } else if (uploadFailed) {
            uploadInfoEl.innerHTML = '<span style="color:#ff4757;">自动上传失败，请手动投稿。</span>';
            if (openUploadBtn) openUploadBtn.style.display = 'inline-block';
        } else {
            uploadInfoEl.innerText = '自动上传状态未知，请检查日志。';
        }
    } else {
        uploadInfoEl.innerText = '点击"去投稿"手动上传到B站。';
        if (openUploadBtn) openUploadBtn.style.display = 'inline-block';
    }

    document.getElementById('completion-modal').style.display = 'flex';
}

function closeModal() {
    document.getElementById('completion-modal').style.display = 'none';
}

function copyVideoPath() {
    const path = document.getElementById('modal-video-path').innerText;
    navigator.clipboard.writeText(path);
    showToast('路径已成功复制到剪贴板！');
}

function openUploadPage() {
    const path = document.getElementById('modal-video-path').innerText;
    closeModal();
    const videoPathInput = document.getElementById('video-path');
    if (videoPathInput) videoPathInput.value = path;
    const matchedTask = latestTasks.find(t => t.final_video_path === path);
    if (matchedTask && matchedTask.first_cover_path) {
        const coverInput = document.getElementById('cover-path');
        if (coverInput && !coverInput.value) coverInput.value = matchedTask.first_cover_path;
    }
    switchPage('upload');
    switchUploadSubTab('upload');
}

function copyConsoleLogs() {
    const logsText = Array.from(document.querySelectorAll('#console div')).map(d => d.textContent).join('\n');
    navigator.clipboard.writeText(logsText);
    showToast('日志已成功复制到剪贴板！');
}

function clearConsoleLogs() {
    document.getElementById('console').innerHTML = '';
}

/* ========== 搜索与分页 ========== */
function renderSkeletonSongs() {
    const grid = document.getElementById('songs-grid');
    grid.innerHTML = Array(8).fill(0).map(() => `
        <div class="skeleton-card">
            <div class="shimmer-sweep"></div>
            <div class="skeleton-art"></div>
            <div class="skeleton-text"></div>
            <div class="skeleton-text short"></div>
        </div>
    `).join('');
}

function handleSearchKey(event) {
    const searchInput = document.getElementById('search-input');
    const searchBtn = document.getElementById('search-btn');
    searchBtn.style.display = searchInput.value.trim() !== '' ? 'inline-block' : 'none';

    if (event.key === 'Enter') {
        event.preventDefault();
        executeSearch();
    }
}

async function executeSearch(keepPage = false) {
    const query = document.getElementById('search-input').value.trim();
    if (!query) return;

    paginationMode = 'search';
    if (!keepPage) {
        currentPage = 0;
        searchCache = {};
    }
    currentSearchQuery = query;

    const cacheKey = `${query}_${currentPage}`;
    if (searchCache[cacheKey]) {
        const cachedData = searchCache[cacheKey];
        allSongs = cachedData.songs || [];
        totalCount = cachedData.total || 0;

        updateSynthesisSubtitle();
        updateActionBar();
        renderSongs();
        document.getElementById('status-display').innerText = `已检索到 ${allSongs.length} 首歌曲，共计 ${totalCount} 首 (来自本地缓存)`;
        updatePaginationControls();
        saveSessionCache();
        document.getElementById('songs-grid').scrollTop = 0;
        return;
    }

    renderSkeletonSongs();
    updateSynthesisSubtitle();
    document.getElementById('clear-search-btn').style.display = 'inline-block';
    document.getElementById('status-display').innerText = '正在云端检索中...';

    try {
        const offset = currentPage * pageSize;
        const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(query)}&limit=${pageSize}&offset=${offset}`);
        if (!res.ok) throw new Error('搜索请求失败');
        const data = await res.json();

        allSongs = data.songs || [];
        totalCount = data.total || 0;
        searchCache[cacheKey] = { songs: allSongs, total: totalCount };

        updateActionBar();
        renderSongs();
        document.getElementById('status-display').innerText = `已检索到 ${allSongs.length} 首歌曲，共计 ${totalCount} 首`;

        updatePaginationControls();
        saveSessionCache();
        document.getElementById('songs-grid').scrollTop = 0;
    } catch (e) {
        document.getElementById('status-display').innerText = '搜索失败，请检查网络';
        document.getElementById('songs-grid').innerHTML = `
            <div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--text-dim);">
                暂无搜索结果或连接超时
            </div>
        `;
        document.getElementById('pagination-controls').style.display = 'none';
    }
}

function updatePaginationControls() {
    const controls = document.getElementById('pagination-controls');
    if (totalCount > pageSize) {
        controls.style.display = 'flex';
        const totalPages = Math.ceil(totalCount / pageSize);
        document.getElementById('current-page-num').innerText = String(currentPage + 1);
        document.getElementById('total-page-num').innerText = String(totalPages);

        const prevBtn = document.getElementById('prev-page-btn');
        const nextBtn = document.getElementById('next-page-btn');

        prevBtn.disabled = currentPage === 0;
        prevBtn.style.opacity = currentPage === 0 ? '0.5' : '1';
        prevBtn.style.cursor = currentPage === 0 ? 'not-allowed' : 'pointer';

        nextBtn.disabled = currentPage >= totalPages - 1;
        nextBtn.style.opacity = currentPage >= totalPages - 1 ? '0.5' : '1';
        nextBtn.style.cursor = currentPage >= totalPages - 1 ? 'not-allowed' : 'pointer';
    } else {
        controls.style.display = 'none';
    }
}

function changePage(direction) {
    const totalPages = Math.ceil(totalCount / pageSize);
    const newPage = currentPage + direction;
    if (newPage >= 0 && newPage < totalPages) {
        currentPage = newPage;
        if (paginationMode === 'search') {
            executeSearch(true);
        } else if (paginationMode === 'playlist') {
            selectPlaylist(activePlaylistId, true);
        }
    }
}

function clearSearch() {
    document.getElementById('search-input').value = '';
    document.getElementById('search-btn').style.display = 'none';
    document.getElementById('clear-search-btn').style.display = 'none';
    currentSearchQuery = '';
    currentPage = 0;
    totalCount = 0;
    paginationMode = 'recommend';
    searchCache = {};
    updateSynthesisSubtitle();
    document.getElementById('pagination-controls').style.display = 'none';
    renderSkeletonSongs();
    fetchSongs();
}

/* ========== 网易云 & B站登录 ========== */
function updateNeteaseUI(isLoggedIn) {
    const statusDiv = document.getElementById('netease-login-status');
    const loginBtn = document.getElementById('netease-login-btn');
    const playlistsContainer = document.getElementById('playlists-container');
    if (!statusDiv || !loginBtn) return;

    if (isLoggedIn) {
        statusDiv.innerHTML = '<span style="color:#2ecc71;">已登录</span>';
        loginBtn.textContent = '重新扫码登录';
        loginBtn.className = 'btn-outline';
        fetchPlaylists();
    } else {
        statusDiv.innerHTML = '<span style="color:#ff4757;">未登录</span>';
        loginBtn.textContent = '扫码登录网易云';
        loginBtn.className = 'btn-primary';
        if (playlistsContainer) {
            playlistsContainer.innerHTML = `
                <div style="text-align: center; padding: 20px; color: var(--text-dim); font-size: 13px;">
                    登录网易云后自动同步歌单
                </div>
            `;
        }
    }
}

async function startNeteaseLogin() {
    document.getElementById('netease-login-modal').style.display = 'flex';
    document.getElementById('netease-qr-wrapper').style.display = 'none';
    document.getElementById('netease-qr-loading').style.display = 'block';
    document.getElementById('netease-qr-loading').innerText = '生成二维码中...';
    document.getElementById('netease-login-msg').innerText = '请使用网易云音乐App扫码';
    document.getElementById('netease-login-msg').className = 'status-info';

    try {
        const res = await fetch(`${API_BASE}/netease/qrcode`);
        const data = await res.json();
        if (data.qr_path) {
            document.getElementById('netease-qr-img').src = data.qr_path;
            document.getElementById('netease-qr-wrapper').style.display = 'inline-block';
            document.getElementById('netease-qr-loading').style.display = 'none';
            pollNeteaseLogin(data.unikey);
        } else {
            document.getElementById('netease-login-msg').innerText = '获取二维码失败: ' + (data.error || '未知错误');
            document.getElementById('netease-login-msg').className = 'status-error';
        }
    } catch (e) {
        document.getElementById('netease-login-msg').innerText = '连接失败: ' + e.message;
        document.getElementById('netease-login-msg').className = 'status-error';
    }
}

function pollNeteaseLogin(unikey) {
    if (neteaseLoginPolling) clearInterval(neteaseLoginPolling);
    isNeteaseChecking = false;
    neteaseLoginPolling = setInterval(async () => {
        if (isNeteaseChecking) return;
        isNeteaseChecking = true;
        try {
            const res = await fetch(`${API_BASE}/netease/check-login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ unikey })
            });
            const data = await res.json();

            if (data.success && data.status === 'success') {
                clearInterval(neteaseLoginPolling);
                document.getElementById('netease-login-msg').innerText = '登录成功，已自动保存配置！';
                document.getElementById('netease-login-msg').className = 'status-success';
                updateNeteaseUI(true);
                setTimeout(() => {
                    closeNeteaseLoginModal();
                    fetchSongs();
                }, 1500);
            } else if (data.status === 'authorizing') {
                document.getElementById('netease-login-msg').innerText = '已在手机扫码，请在App内点击【确认登录】';
                document.getElementById('netease-login-msg').className = 'status-info';
            } else if (data.status === 'expired') {
                clearInterval(neteaseLoginPolling);
                document.getElementById('netease-login-msg').innerText = '二维码已失效，请重新生成！';
                document.getElementById('netease-login-msg').className = 'status-error';
            }
        } catch (e) {
        } finally {
            isNeteaseChecking = false;
        }
    }, 2000);
}

function closeNeteaseLoginModal() {
    document.getElementById('netease-login-modal').style.display = 'none';
    if (neteaseLoginPolling) clearInterval(neteaseLoginPolling);
}

async function startBilibiliLogin() {
    document.getElementById('bilibili-login-modal').style.display = 'flex';
    document.getElementById('bilibili-qr-wrapper').style.display = 'none';
    document.getElementById('bilibili-qr-loading').style.display = 'block';
    document.getElementById('bilibili-login-msg').innerText = '请使用B站App扫码';
    document.getElementById('bilibili-login-msg').className = 'status-info';
    try {
        const res = await fetch(`${API_BASE}/bilibili/qrcode`);
        const data = await res.json();
        if (data.qr_path) {
            document.getElementById('bilibili-qr-img').src = data.qr_path;
            document.getElementById('bilibili-qr-wrapper').style.display = 'inline-block';
            document.getElementById('bilibili-qr-loading').style.display = 'none';
            pollBilibiliLogin(data.raw_json);
        } else {
            document.getElementById('bilibili-login-msg').innerText = '获取二维码失败: ' + (data.error || '未知错误');
            document.getElementById('bilibili-login-msg').className = 'status-error';
        }
    } catch (e) {
        document.getElementById('bilibili-login-msg').innerText = '连接失败: ' + e.message;
        document.getElementById('bilibili-login-msg').className = 'status-error';
    }
}

function pollBilibiliLogin(rawJson) {
    if (loginPolling) clearInterval(loginPolling);
    isBilibiliChecking = false;
    loginPolling = setInterval(async () => {
        if (isBilibiliChecking) return;
        isBilibiliChecking = true;
        try {
            const res = await fetch(`${API_BASE}/bilibili/check-login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(rawJson)
            });
            const data = await res.json();
            if (data.success) {
                clearInterval(loginPolling);
                document.getElementById('bilibili-login-status').innerHTML = '<span style="color:#2ecc71;">已登录</span>';
                document.getElementById('bilibili-login-msg').innerText = '登录成功！';
                document.getElementById('bilibili-login-msg').className = 'status-success';
                setTimeout(closeBilibiliLoginModal, 1500);
            } else if (data.status === 'error') {
                clearInterval(loginPolling);
                document.getElementById('bilibili-login-msg').innerText = '登录失败: ' + (data.error || '二维码可能已超时');
                document.getElementById('bilibili-login-msg').className = 'status-error';
            }
        } catch (e) {
        } finally {
            isBilibiliChecking = false;
        }
    }, 2000);
}

function closeBilibiliLoginModal() {
    document.getElementById('bilibili-login-modal').style.display = 'none';
    if (loginPolling) clearInterval(loginPolling);
}

async function checkBilibiliLoginStatus() {
    try {
        const res = await fetch(`${API_BASE}/bilibili/check-cookie`);
        const data = await res.json();
        document.getElementById('bilibili-login-status').innerHTML = data.logged_in
            ? '<span style="color:#2ecc71;">已登录</span>'
            : '<span style="color:#ff4757;">未登录</span>';
    } catch (e) {}
}

/* ========== HTML5 音频在线试听播放器 ========== */
function playSongById(id) {
    const song = allSongs.find(s => s.id === id);
    if (!song) return;
    playSong(song.id, song.name, (song.artists || []).join(', '), song.album_pic);
}

async function playSong(id, name, artist, albumPic) {
    if (!globalAudio) globalAudio = document.getElementById('global-audio-player');
    if (!playerBar) playerBar = document.getElementById('music-player-bar');

    if (currentPlayingSongId === id) {
        if (globalAudio.paused) {
            globalAudio.play().catch(err => showToast(`播放失败: ${err.message}`, 'error'));
        } else {
            globalAudio.pause();
        }
        return;
    }

    currentPlayingSongId = id;
    document.getElementById('player-song-name').innerText = '加载中...';
    document.getElementById('player-artist').innerText = name;
    document.getElementById('player-cover').src = albumPic || DEFAULT_COVER;
    playerBar.classList.add('visible');

    document.querySelectorAll('.song-card').forEach(c => c.classList.remove('playing'));
    document.querySelectorAll('.play-btn .play-icon').forEach(i => i.style.display = 'block');
    document.querySelectorAll('.play-btn .pause-icon').forEach(i => i.style.display = 'none');
    document.querySelectorAll('.audio-wave-anim').forEach(w => w.style.display = 'none');

    try {
        const res = await fetch(`${API_BASE}/netease/song-url?id=${encodeURIComponent(id)}`);
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || '未找到播放直链');
        }
        const data = await res.json();
        if (!data.url) throw new Error('试听链接为空');

        globalAudio.src = data.url;
        await globalAudio.play();

        document.getElementById('player-song-name').innerText = name;
        document.getElementById('player-artist').innerText = artist;
        syncCardPlayingUI(id, true);
    } catch (err) {
        showToast(`试听失败: ${err.message}`, 'error');
        document.getElementById('player-song-name').innerText = '播放失败';
        document.getElementById('player-artist').innerText = name;
        playerBar.classList.remove('visible');
        currentPlayingSongId = null;
    }
}

function syncCardPlayingUI(id, isPlaying) {
    const card = document.querySelector(`.song-card[data-id="${id}"]`);
    if (!card) return;
    if (isPlaying) {
        card.classList.add('playing');
        card.querySelector('.play-btn .play-icon').style.display = 'none';
        card.querySelector('.play-btn .pause-icon').style.display = 'block';
        card.querySelector('.audio-wave-anim').style.display = 'flex';
    } else {
        card.classList.remove('playing');
        card.querySelector('.play-btn .play-icon').style.display = 'block';
        card.querySelector('.play-btn .pause-icon').style.display = 'none';
        card.querySelector('.audio-wave-anim').style.display = 'none';
    }
}

function syncPlayPauseUI(isPlaying) {
    const playIcon = document.getElementById('bar-play-icon');
    const pauseIcon = document.getElementById('bar-pause-icon');
    const coverImg = document.getElementById('player-cover');

    playIcon.style.display = isPlaying ? 'none' : 'block';
    pauseIcon.style.display = isPlaying ? 'block' : 'none';
    coverImg.classList.toggle('spinning', isPlaying);
    if (currentPlayingSongId) syncCardPlayingUI(currentPlayingSongId, isPlaying);
}

function togglePlayPause() {
    if (!globalAudio) return;
    if (globalAudio.paused) {
        globalAudio.play().catch(err => showToast(`播放失败: ${err.message}`, 'error'));
    } else {
        globalAudio.pause();
    }
}

function updatePlayerProgress() {
    if (!globalAudio) return;
    const cur = globalAudio.currentTime || 0;
    const dur = globalAudio.duration || 0;
    if (dur > 0) {
        const pct = (cur / dur) * 100;
        document.getElementById('player-timeline-fill').style.width = pct + '%';
        document.getElementById('player-timeline-knob').style.left = pct + '%';
    }
    document.getElementById('player-time-current').innerText = formatDuration(cur * 1000);
}

function seekAudio(e) {
    if (!globalAudio || !globalAudio.duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    globalAudio.currentTime = pct * globalAudio.duration;
    document.getElementById('player-timeline-fill').style.width = (pct * 100) + '%';
    document.getElementById('player-timeline-knob').style.left = (pct * 100) + '%';
}

function adjustVolume(e) {
    if (!globalAudio) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    globalAudio.volume = pct;
    document.getElementById('player-volume-fill').style.width = (pct * 100) + '%';
}

function closePlayerBar() {
    if (globalAudio) globalAudio.pause();
    if (playerBar) playerBar.classList.remove('visible');
    document.querySelectorAll('.song-card').forEach(c => c.classList.remove('playing'));
    document.querySelectorAll('.play-btn .play-icon').forEach(i => i.style.display = 'block');
    document.querySelectorAll('.play-btn .pause-icon').forEach(i => i.style.display = 'none');
    document.querySelectorAll('.audio-wave-anim').forEach(w => w.style.display = 'none');
    currentPlayingSongId = null;
}

function playNextOrPrev(direction) {
    if (allSongs.length === 0) return;
    let nextIndex = 0;
    if (currentPlayingSongId) {
        const curIdx = allSongs.findIndex(s => s.id === currentPlayingSongId);
        if (curIdx !== -1) {
            nextIndex = (curIdx + direction + allSongs.length) % allSongs.length;
        }
    }
    const nextSong = allSongs[nextIndex];
    if (nextSong) {
        playSong(nextSong.id, nextSong.name, (nextSong.artists || []).join(', '), nextSong.album_pic);
    }
}

/* ========== B站文件选择与投稿 ========== */
window.onFileSelected = function (input) {
    const file = input.files[0];
    if (file) uploadLocalAsset(file, 'video-path', '正在上传视频中...', '上传视频失败');
};

window.onCoverSelected = function (input) {
    const file = input.files[0];
    if (file) uploadLocalAsset(file, 'cover-path', '正在上传封面中...', '上传封面失败');
};

async function uploadLocalAsset(file, inputId, pendingMsg, errPrefix) {
    const targetInput = document.getElementById(inputId);
    targetInput.value = pendingMsg;
    targetInput.disabled = true;

    const formData = new FormData();
    formData.append('file', file);
    try {
        const res = await fetch(`${API_BASE}/bilibili/upload-file`, { method: 'POST', body: formData });
        const data = await res.json();
        if (res.ok && data.path) {
            targetInput.value = data.path;
        } else {
            showToast(`${errPrefix}: ${data.detail || data.error || '未知错误'}`, 'error');
            targetInput.value = '';
        }
    } catch (e) {
        showToast(`${errPrefix}: ${e.message}`, 'error');
        targetInput.value = '';
    } finally {
        targetInput.disabled = false;
    }
}

function renderTags(container, tagList, tagType) {
    container.innerHTML = tagList.map((t, idx) =>
        `<span class="tag">${escapeHtml(t)} <span class="remove" data-tag-type="${tagType}" data-tag-index="${idx}">×</span></span>`
    ).join('');
}

function addTag() {
    const input = document.getElementById('tag-input');
    const val = input.value.trim();
    if (val && !tags.includes(val)) {
        tags.push(val);
        renderTags(document.getElementById('tag-container'), tags, 'upload');
    }
    input.value = '';
}

function addFormatTag() {
    const input = document.getElementById('format-tag-input');
    const val = input.value.trim();
    if (val && !formatTags.includes(val)) {
        formatTags.push(val);
        renderTags(document.getElementById('format-tag-container'), formatTags, 'format');
    }
    input.value = '';
}

function toggleCustomCover() {
    document.getElementById('custom-cover-group').style.display =
        document.getElementById('format-cover').value === 'custom' ? 'block' : 'none';
}

function toggleCustomDesc() {
    document.getElementById('custom-desc-group').style.display =
        document.getElementById('format-description').value === 'custom' ? 'block' : 'none';
}

async function startUpload() {
    const resultDiv = document.getElementById('upload-result');
    const videoPath = document.getElementById('video-path').value.trim();
    if (!videoPath) {
        resultDiv.innerHTML = '<div class="status-error">请输入视频文件路径</div>';
        return;
    }
    resultDiv.innerHTML = '<div class="status-info">正在上传...</div>';
    try {
        const res = await fetch(`${API_BASE}/bilibili/upload`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                video_path: videoPath,
                title: document.getElementById('title').value,
                description: document.getElementById('description').value,
                tags: tags,
                cover: document.getElementById('cover-path').value.trim()
            })
        });
        const data = await res.json();
        if (res.ok && (data.success || data.bvid)) {
            const bvidMsg = data.bvid ? ` (BVID: ${escapeHtml(data.bvid)})` : '';
            resultDiv.innerHTML = `<div class="status-success">上传成功！${bvidMsg}</div>`;
        } else {
            resultDiv.innerHTML = `<div class="status-error">上传失败: ${escapeHtml(data.detail || data.error || JSON.stringify(data))}</div>`;
        }
    } catch (e) {
        resultDiv.innerHTML = `<div class="status-error">请求失败: ${escapeHtml(e.message)}</div>`;
    }
}

/* ========== B站投稿模板格式管理 ========== */
async function loadFormats() {
    try {
        const res = await fetch(`${API_BASE}/bilibili/upload-formats`);
        if (!res.ok) return;
        currentFormats = await res.json();
        renderFormatCards();
        renderSidebarFormats();
    } catch (e) {}
}

function renderFormatCards() {
    const container = document.getElementById('format-manager');
    if (!container) return;
    container.innerHTML = currentFormats.map((f, i) => `
        <div class="format-card" data-format-index="${i}">
            <h4>${escapeHtml(f.name)}</h4>
            <div style="font-size:13px;">标题: ${escapeHtml(f.title)}</div>
            <div style="font-size:13px;">封面: ${f.cover === 'first_song' ? '第一首' : '自定义'}</div>
            <div class="tags">${(f.tags || []).map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('')}</div>
            <div class="format-actions">
                <button class="btn-danger" data-format-delete="${i}">删除</button>
            </div>
        </div>
    `).join('');
}

function renderSidebarFormats() {
    const sidebar = document.getElementById('sidebar-formats');
    if (!sidebar) return;
    sidebar.innerHTML = currentFormats.map((f, i) =>
        `<div style="padding:8px 0; font-size:13px; cursor:pointer; color:var(--accent);" data-format-apply="${i}">${escapeHtml(f.name)}</div>`
    ).join('') || '暂无格式';
}

function applyFormatByIndex(idx) {
    const format = currentFormats[idx];
    if (!format) return;

    document.getElementById('title').value = format.title || '';

    const curVideoPath = (document.getElementById('video-path').value || '').trim();
    const matchedTask = latestTasks.find(t => t.final_video_path && t.final_video_path === curVideoPath)
        || [...latestTasks].reverse().find(t => t.song_list_text);

    if (format.cover === 'first_song') {
        document.getElementById('cover-path').value = (matchedTask && matchedTask.first_cover_path) ? matchedTask.first_cover_path : '';
    } else {
        document.getElementById('cover-path').value = format.cover_custom || '';
    }

    if (format.description === 'song_list') {
        document.getElementById('description').value = matchedTask ? matchedTask.song_list_text : '';
    } else if (format.description === 'custom') {
        document.getElementById('description').value = format.description_custom || '';
    }

    tags = [...(format.tags || [])];
    renderTags(document.getElementById('tag-container'), tags, 'upload');
}

function editFormat(idx) {
    const f = currentFormats[idx];
    if (!f) return;
    document.getElementById('format-name').value = f.name || '';
    document.getElementById('format-title').value = f.title || '';
    document.getElementById('format-cover').value = f.cover || 'first_song';
    document.getElementById('format-cover-custom').value = f.cover_custom || '';
    document.getElementById('format-description').value = f.description || 'song_list';
    document.getElementById('format-description-custom').value = f.description_custom || '';
    formatTags = [...(f.tags || [])];
    renderTags(document.getElementById('format-tag-container'), formatTags, 'format');
    toggleCustomCover();
    toggleCustomDesc();
}

async function saveFormat() {
    const name = document.getElementById('format-name').value.trim();
    if (!name) {
        showToast('请填写格式名称', 'error');
        return;
    }
    const data = {
        name,
        title: document.getElementById('format-title').value,
        cover: document.getElementById('format-cover').value,
        cover_custom: document.getElementById('format-cover-custom').value,
        description: document.getElementById('format-description').value,
        description_custom: document.getElementById('format-description-custom').value,
        tags: formatTags
    };
    try {
        const res = await fetch(`${API_BASE}/bilibili/upload-formats`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!res.ok) throw new Error('保存失败');
        showToast('格式模板已保存');
        await loadFormats();
        await loadUploadFormats();
    } catch (e) {
        showToast('保存格式失败', 'error');
    }
}

async function deleteFormatByIndex(idx) {
    const f = currentFormats[idx];
    if (!f) return;
    if (!confirm(`确认删除格式 "${f.name}"?`)) return;
    try {
        const res = await fetch(`${API_BASE}/bilibili/upload-formats/${encodeURIComponent(f.name)}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('删除失败');
        showToast('格式模板已删除');
        await loadFormats();
        await loadUploadFormats();
    } catch (e) {
        showToast('删除格式失败', 'error');
    }
}

function resetFormatForm() {
    document.getElementById('format-name').value = '';
    document.getElementById('format-title').value = '';
    document.getElementById('format-cover').value = 'first_song';
    document.getElementById('format-cover-custom').value = '';
    document.getElementById('format-description').value = 'song_list';
    document.getElementById('format-description-custom').value = '';
    formatTags = ['音乐', '网易云音乐'];
    renderTags(document.getElementById('format-tag-container'), formatTags, 'format');
    toggleCustomCover();
    toggleCustomDesc();
}

/* ========== 事件委托与初始化 ========== */
function bindDelegatedEvents() {
    const songsGrid = document.getElementById('songs-grid');
    if (songsGrid) {
        songsGrid.addEventListener('click', (e) => {
            const playBtn = e.target.closest('.play-btn');
            if (playBtn) {
                e.stopPropagation();
                playSongById(Number(playBtn.getAttribute('data-play-id')));
                return;
            }
            const card = e.target.closest('.song-card');
            if (card) {
                toggleSong(Number(card.getAttribute('data-id')));
            }
        });
    }

    const playlistsContainer = document.getElementById('playlists-container');
    if (playlistsContainer) {
        playlistsContainer.addEventListener('click', (e) => {
            const item = e.target.closest('.playlist-item');
            if (item) {
                selectPlaylist(item.getAttribute('data-playlist-id'));
            }
        });
    }

    const queueDiv = document.getElementById('selection-queue');
    if (queueDiv) {
        queueDiv.addEventListener('click', (e) => {
            const rm = e.target.closest('.queue-remove-btn');
            if (rm) {
                e.stopPropagation();
                removeSongFromQueue(Number(rm.getAttribute('data-remove-id')));
            }
        });
        queueDiv.addEventListener('dragstart', (e) => {
            const item = e.target.closest('.queue-item');
            if (!item) return;
            item.classList.add('dragging');
            dragSrcId = item.getAttribute('data-id');
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', dragSrcId);
        });
        queueDiv.addEventListener('dragover', (e) => {
            if (e.target.closest('.queue-item')) {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
            }
        });
        queueDiv.addEventListener('drop', (e) => {
            const targetItem = e.target.closest('.queue-item');
            if (!targetItem) return;
            e.stopPropagation();
            e.preventDefault();
            const targetId = targetItem.getAttribute('data-id');
            if (dragSrcId && dragSrcId !== targetId) {
                const srcIndex = selectedSongs.findIndex(s => String(s.id) === String(dragSrcId));
                const targetIndex = selectedSongs.findIndex(s => String(s.id) === String(targetId));
                if (srcIndex !== -1 && targetIndex !== -1) {
                    const [moved] = selectedSongs.splice(srcIndex, 1);
                    selectedSongs.splice(targetIndex, 0, moved);
                    updateActionBar();
                    syncSongCardsSelection();
                }
            }
        });
        queueDiv.addEventListener('dragend', () => {
            document.querySelectorAll('.queue-item').forEach(item => item.classList.remove('dragging'));
        });
    }

    const handleTaskListClick = (e) => {
        const actionBtn = e.target.closest('[data-task-action]');
        if (actionBtn) {
            e.stopPropagation();
            const action = actionBtn.getAttribute('data-task-action');
            const id = actionBtn.getAttribute('data-task-id');
            if (action === 'cancel') cancelTask(id);
            else if (action === 'delete') deleteTask(id);
            return;
        }
        const selectCard = e.target.closest('[data-task-select]');
        if (selectCard) {
            selectTask(selectCard.getAttribute('data-task-select'));
        }
    };

    const taskQueueCard = document.getElementById('task-queue-card');
    if (taskQueueCard) taskQueueCard.addEventListener('click', handleTaskListClick);
    const logsContainer = document.getElementById('logs-task-container');
    if (logsContainer) logsContainer.addEventListener('click', handleTaskListClick);

    const sidebarFormats = document.getElementById('sidebar-formats');
    if (sidebarFormats) {
        sidebarFormats.addEventListener('click', (e) => {
            const el = e.target.closest('[data-format-apply]');
            if (el) applyFormatByIndex(Number(el.getAttribute('data-format-apply')));
        });
    }

    const formatManager = document.getElementById('format-manager');
    if (formatManager) {
        formatManager.addEventListener('click', (e) => {
            const delBtn = e.target.closest('[data-format-delete]');
            if (delBtn) {
                e.stopPropagation();
                deleteFormatByIndex(Number(delBtn.getAttribute('data-format-delete')));
                return;
            }
            const card = e.target.closest('[data-format-index]');
            if (card) editFormat(Number(card.getAttribute('data-format-index')));
        });
    }

    document.addEventListener('click', (e) => {
        const rmTag = e.target.closest('[data-tag-type][data-tag-index]');
        if (!rmTag) return;
        const type = rmTag.getAttribute('data-tag-type');
        const idx = Number(rmTag.getAttribute('data-tag-index'));
        if (type === 'upload') {
            tags.splice(idx, 1);
            renderTags(document.getElementById('tag-container'), tags, 'upload');
        } else if (type === 'format') {
            formatTags.splice(idx, 1);
            renderTags(document.getElementById('format-tag-container'), formatTags, 'format');
        }
    });

    const tagInput = document.getElementById('tag-input');
    if (tagInput) {
        tagInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); addTag(); }
        });
    }
    const formatTagInput = document.getElementById('format-tag-input');
    if (formatTagInput) {
        formatTagInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); addFormatTag(); }
        });
    }
}

function initAudioPlayer() {
    globalAudio = document.getElementById('global-audio-player');
    playerBar = document.getElementById('music-player-bar');
    if (!globalAudio) return;

    globalAudio.addEventListener('timeupdate', updatePlayerProgress);
    globalAudio.addEventListener('durationchange', () => {
        document.getElementById('player-time-total').innerText = formatDuration(globalAudio.duration * 1000);
    });
    globalAudio.addEventListener('ended', () => playNextOrPrev(1));
    globalAudio.addEventListener('play', () => syncPlayPauseUI(true));
    globalAudio.addEventListener('pause', () => syncPlayPauseUI(false));
    globalAudio.addEventListener('error', () => {
        if (currentPlayingSongId) {
            showToast('音频流加载失败，可能链接已失效', 'error');
        }
    });
}

async function loadInitial() {
    try {
        const res = await fetch(`${API_BASE}/config`);
        const config = await res.json();
        const isLoggedIn = Boolean(
            config.has_netease_cookie ?? (config.netease_cookie && config.netease_cookie.trim() !== '')
        );
        updateNeteaseUI(isLoggedIn);

        if (isLoggedIn) {
            const cachedSongs = sessionStorage.getItem('music_pipeline_all_songs');
            if (cachedSongs) {
                try {
                    allSongs = JSON.parse(cachedSongs);
                    activePlaylistId = sessionStorage.getItem('music_pipeline_active_playlist_id') || 'daily_recommend';
                    paginationMode = sessionStorage.getItem('music_pipeline_pagination_mode') || 'recommend';
                    currentPage = parseInt(sessionStorage.getItem('music_pipeline_current_page') || '0', 10) || 0;
                    totalCount = parseInt(sessionStorage.getItem('music_pipeline_total_count') || '0', 10) || 0;
                    currentSearchQuery = sessionStorage.getItem('music_pipeline_search_query') || '';

                    renderPlaylists();
                    updateActionBar();
                    renderSongs();

                    if (paginationMode === 'search') {
                        document.getElementById('search-input').value = currentSearchQuery;
                        document.getElementById('clear-search-btn').style.display = 'inline-block';
                    }
                    updateSynthesisSubtitle();
                    updatePaginationControls();
                    document.getElementById('status-display').innerText = `已从本地缓存加载 ${allSongs.length} 首歌曲`;
                    return;
                } catch (cacheErr) {
                    console.error('恢复缓存失败', cacheErr);
                }
            }
            fetchSongs();
        }
    } catch (e) {}
}

document.addEventListener('DOMContentLoaded', () => {
    try {
        const saved = sessionStorage.getItem('music_pipeline_selected_songs');
        if (saved) selectedSongs = JSON.parse(saved);
    } catch (e) {}

    bindDelegatedEvents();
    initAudioPlayer();
    updateActionBar();
    renderTags(document.getElementById('tag-container'), tags, 'upload');
    renderTags(document.getElementById('format-tag-container'), formatTags, 'format');

    loadInitial();
    loadUploadFormats();
    loadFormats();
    checkBilibiliLoginStatus();
    checkQueueOnce();
    startStatusPolling();

    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('login') === '1') {
        window.history.replaceState({}, document.title, window.location.pathname);
        setTimeout(startNeteaseLogin, 300);
    }

    let initialPage = urlParams.get('page');
    const initialVideoPath = urlParams.get('video_path');
    if (!initialPage) {
        initialPage = sessionStorage.getItem('music_pipeline_active_page') || 'synthesis';
    } else {
        window.history.replaceState({}, document.title, window.location.pathname);
    }

    if (initialVideoPath) {
        const videoPathInput = document.getElementById('video-path');
        if (videoPathInput) videoPathInput.value = initialVideoPath;
    }

    switchPage(initialPage);

    setInterval(() => {
        fetch(`${API_BASE}/heartbeat`, { method: 'POST' }).catch(() => {});
    }, 3000);
});
