/**
 * Voxxwire — Frontend Application Logic
 * Communicates with the Python backend via pywebview's JS bridge.
 */

// ═══════════════════════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════════════════════
let isRunning = false;
let selectedModel = 'small';
let pollInterval = null;
let settingsDirty = false;
let appliedSettingsKey = null;
let savedSettingsKey = null;
let lastEngineAction = 'start'; // 'start' or 'restart' — which action Retry repeats
let transcriptLog = []; // full session history for the Download Transcript button (unlike the on-screen panels, never trimmed)

// ═══════════════════════════════════════════════════════════════════════════
//  DOM REFERENCES
// ═══════════════════════════════════════════════════════════════════════════
const $ = (id) => document.getElementById(id);

const statusDot = $('statusDot');
const statusText = $('statusText');
const startBtn = $('startBtn');
const micMessages = $('micMessages');
const lbMessages = $('lbMessages');
const micWelcome = $('micWelcome');
const lbWelcome = $('lbWelcome');
const micOutputScroll = $('micOutputScroll');
const lbOutputScroll = $('lbOutputScroll');
const logText = $('logText');
const logArea = $('logArea');
const logToggle = $('logToggle');
const saveBtn = $('saveBtn');
const restartBanner = $('restartBanner');
const restartBtn = $('restartBtn');
const engineOverlay = $('engineOverlay');
const engineOverlayTitle = $('engineOverlayTitle');
const engineOverlayMessage = $('engineOverlayMessage');
const engineOverlayProgressBar = $('engineOverlayProgressBar');
const engineOverlayCancelBtn = $('engineOverlayCancelBtn');
const engineOverlayRetryBtn = $('engineOverlayRetryBtn');
const downloadTranscriptBtn = $('downloadTranscriptBtn');
const transcriptCount = $('transcriptCount');
const micChannelStatus = $('micChannelStatus');
const lbChannelStatus = $('lbChannelStatus');

// ═══════════════════════════════════════════════════════════════════════════
//  INITIALIZATION
// ═══════════════════════════════════════════════════════════════════════════
window.addEventListener('pywebviewready', async () => {
    console.log('pywebview bridge ready');
    await initApp();
});

async function initApp() {
    try {
        // Load devices
        const devices = await pywebview.api.get_devices();
        populateDevices(devices);

        // Load languages
        const languages = await pywebview.api.get_languages();
        populateLanguages(languages);

        // Load current settings
        const settings = await pywebview.api.get_settings();
        applySettings(settings);
        savedSettingsKey = JSON.stringify(gatherSettings());
        appliedSettingsKey = savedSettingsKey;
        saveBtn.disabled = true;

    } catch (e) {
        console.error('Init error:', e);
        appendLog('⚠ Failed to initialize: ' + e.message);
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  POPULATE UI
// ═══════════════════════════════════════════════════════════════════════════
function populateDevices(devices) {
    const micSelect = $('micDevice');
    const lbSelect = $('loopbackDevice');

    micSelect.innerHTML = '';
    lbSelect.innerHTML = '';

    // Mic uses regular sounddevice input devices.
    devices.inputs.forEach(d => {
        micSelect.add(new Option(d.name, d.index));
    });

    // Loopback uses real WASAPI loopback devices (a distinct index
    // namespace from sounddevice) — every entry here genuinely captures
    // speaker/headphone output, never the microphone, so "You" and
    // "Remote" can never overlap.
    const lbDevices = devices.loopbacks || [];
    lbDevices.forEach(d => {
        lbSelect.add(new Option(d.name, d.index));
    });

    // Auto-select best microphone (prefer headset/headphone, then default)
    const micDevices = devices.inputs;
    const headsetMic = micDevices.find(d => /headset|headphone|earphone|airpod|buds/i.test(d.name));
    const defaultMic = micDevices.find(d => /microphone|mic|default/i.test(d.name));
    const bestMic = headsetMic || defaultMic || micDevices[0];
    if (bestMic) {
        micSelect.value = bestMic.index;
        $('micDeviceName').textContent = truncateDeviceName(bestMic.name);
    } else {
        $('micDeviceName').textContent = 'No device found';
    }

    // Auto-select the default output's loopback device
    const bestLb = lbDevices[0];
    if (bestLb) {
        lbSelect.value = bestLb.index;
        $('lbDeviceName').textContent = truncateDeviceName(bestLb.name);
    } else {
        $('lbDeviceName').textContent = 'No loopback device found';
    }

    // Update chip names when selects change manually
    micSelect.addEventListener('change', () => {
        const selected = micSelect.options[micSelect.selectedIndex];
        if (selected) $('micDeviceName').textContent = truncateDeviceName(selected.text);
    });
    lbSelect.addEventListener('change', () => {
        const selected = lbSelect.options[lbSelect.selectedIndex];
        if (selected) $('lbDeviceName').textContent = truncateDeviceName(selected.text);
    });
}

function truncateDeviceName(name) {
    // Clean up common prefixes and truncate if too long
    let clean = name.replace(/^\(\d+\)\s*/, '').replace(/\s*\(.*?\)\s*$/, '').trim();
    return clean.length > 30 ? clean.substring(0, 28) + '…' : clean;
}

function populateLanguages(languages) {
    const selects = ['micSrcLang', 'micTgtLang', 'lbSrcLang', 'lbTgtLang'];
    selects.forEach(id => {
        const sel = $(id);
        sel.innerHTML = '';
        languages.forEach(lang => {
            sel.add(new Option(lang.name, lang.code));
        });
    });
}

function applySettings(s) {
    // Devices
    const micSelect = $('micDevice');
    const lbSelect = $('loopbackDevice');
    micSelect.value = s.mic_device ?? '';
    lbSelect.value = s.loopback_device ?? '';

    // A persisted loopback_device may be stale (e.g. an old sounddevice
    // index from before the switch to WASAPI loopback devices, which use
    // a different index namespace) — fall back to the first real
    // loopback option rather than leaving nothing selected.
    if (lbSelect.selectedIndex === -1 && lbSelect.options.length > 0) {
        lbSelect.selectedIndex = 0;
    }

    // Update chip names to reflect applied settings
    const micOpt = micSelect.options[micSelect.selectedIndex];
    if (micOpt) $('micDeviceName').textContent = truncateDeviceName(micOpt.text);
    const lbOpt = lbSelect.options[lbSelect.selectedIndex];
    if (lbOpt) $('lbDeviceName').textContent = truncateDeviceName(lbOpt.text);

    // Languages
    $('micSrcLang').value = s.mic_src_lang;
    $('micTgtLang').value = s.mic_tgt_lang;
    $('lbSrcLang').value = s.lb_src_lang;
    $('lbTgtLang').value = s.lb_tgt_lang;

    // Model
    selectedModel = s.whisper_model;
    document.querySelectorAll('.model-card').forEach(card => {
        card.classList.toggle('active', card.dataset.value === selectedModel);
    });

    // Toggles
    $('toggleSubtitles').checked = s.subtitles;
    $('toggleMic').checked = s.mic_channel;
    $('toggleLoopback').checked = s.loopback_channel;
}

// ═══════════════════════════════════════════════════════════════════════════
//  EVENTS
// ═══════════════════════════════════════════════════════════════════════════

// Start / Stop button
startBtn.addEventListener('click', async () => {
    if (startBtn.disabled) return; // guard against double-clicks firing overlapping start/stop calls
    if (!isRunning) {
        await startEngine();
    } else {
        await stopEngine();
    }
});

// Save configuration button
saveBtn.addEventListener('click', saveConfig);

// Download transcript button
downloadTranscriptBtn.addEventListener('click', downloadTranscript);

// Restart & Apply button
restartBtn.addEventListener('click', restartEngine);

// Engine overlay: Cancel (while loading) / Dismiss (after an error)
engineOverlayCancelBtn.addEventListener('click', async () => {
    hideEngineOverlay();
    await stopEngine();
});

// Engine overlay: Retry after a failed start
engineOverlayRetryBtn.addEventListener('click', async () => {
    if (lastEngineAction === 'restart') {
        await restartEngine();
    } else {
        await startEngine();
    }
});

// Model card selection
document.querySelectorAll('.model-card').forEach(card => {
    card.addEventListener('click', () => {
        document.querySelectorAll('.model-card').forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        selectedModel = card.dataset.value;
        onSettingsChanged();
    });
});

// Track changes to language/device/toggle settings while the engine is
// running so we can prompt the user to restart & reload the models —
// otherwise a language change silently keeps using the old pipeline.
['micSrcLang', 'micTgtLang', 'lbSrcLang', 'lbTgtLang', 'micDevice', 'loopbackDevice']
    .forEach(id => $(id).addEventListener('change', onSettingsChanged));
['toggleSubtitles', 'toggleMic', 'toggleLoopback']
    .forEach(id => $(id).addEventListener('change', onSettingsChanged));

// Log toggle
logToggle.addEventListener('click', () => {
    logArea.classList.toggle('expanded');
});

// Clear mic output
$('clearMicBtn').addEventListener('click', () => {
    micMessages.innerHTML = '';
    micWelcome.classList.remove('hidden');
});

// Clear loopback output
$('clearLbBtn').addEventListener('click', () => {
    lbMessages.innerHTML = '';
    lbWelcome.classList.remove('hidden');
});

// Device chip toggles — show/hide the dropdown
$('micDeviceChangeBtn').addEventListener('click', () => {
    $('micDeviceSelectWrap').classList.toggle('visible');
});
$('lbDeviceChangeBtn').addEventListener('click', () => {
    $('lbDeviceSelectWrap').classList.toggle('visible');
});

// ═══════════════════════════════════════════════════════════════════════════
//  ENGINE CONTROL
// ═══════════════════════════════════════════════════════════════════════════
function gatherSettings() {
    return {
        mic_device: parseInt($('micDevice').value) || 0,
        loopback_device: parseInt($('loopbackDevice').value) || 0,
        mic_src_lang: $('micSrcLang').value,
        mic_tgt_lang: $('micTgtLang').value,
        lb_src_lang: $('lbSrcLang').value,
        lb_tgt_lang: $('lbTgtLang').value,
        whisper_model: selectedModel,
        subtitles: $('toggleSubtitles').checked,
        mic_channel: $('toggleMic').checked,
        loopback_channel: $('toggleLoopback').checked,
    };
}

async function startEngine() {
    lastEngineAction = 'start';
    const settings = gatherSettings();

    setStatus('starting', 'Starting…');
    setRunning(true);
    showEngineOverlay('Starting translator…', 'Warming things up…');
    logArea.classList.add('expanded');
    appendLog('Starting translator engine…');
    startBtn.disabled = true;
    restartBtn.disabled = true;

    try {
        const started = await pywebview.api.start_engine(settings);
        if (!started) {
            appendLog('⚠ Engine was already running — ignored duplicate start.\n');
            hideEngineOverlay();
        } else {
            appliedSettingsKey = JSON.stringify(settings);
            savedSettingsKey = appliedSettingsKey;
            saveBtn.disabled = true;
            setSettingsDirty(false);
            startPolling();
        }
    } catch (e) {
        appendLog('❌ Failed to start: ' + e.message);
        setStatus('error', 'Error');
        setRunning(false);
        showEngineError('Failed to start the translator: ' + e.message);
    } finally {
        startBtn.disabled = false;
        restartBtn.disabled = false;
    }
}

async function stopEngine() {
    appendLog('Stopping translator…');
    startBtn.disabled = true;
    restartBtn.disabled = true;
    try {
        await pywebview.api.stop_engine();
    } catch (e) {
        console.error('Stop error:', e);
    }
    stopPolling();
    setStatus('idle', 'Ready');
    setRunning(false);
    hideEngineOverlay();
    startBtn.disabled = false;
    restartBtn.disabled = false;
}

async function saveConfig() {
    const settings = gatherSettings();
    try {
        await pywebview.api.save_settings(settings);
        savedSettingsKey = JSON.stringify(settings);
        saveBtn.disabled = true;
        appendLog('💾 Configuration saved.\n');
    } catch (e) {
        appendLog('❌ Failed to save configuration: ' + e.message + '\n');
    }
}

async function restartEngine() {
    if (restartBtn.disabled) return; // guard against double-clicks firing overlapping restarts
    lastEngineAction = 'restart';
    const settings = gatherSettings();

    setStatus('starting', 'Reloading models…');
    showEngineOverlay('Reloading models…', 'Applying your new settings…');
    logArea.classList.add('expanded');
    appendLog('🔄 Restarting engine to apply new settings…\n');
    startBtn.disabled = true;
    restartBtn.disabled = true;

    try {
        await pywebview.api.restart_engine(settings);
        appliedSettingsKey = JSON.stringify(settings);
        savedSettingsKey = appliedSettingsKey;
        saveBtn.disabled = true;
        setSettingsDirty(false);
        setRunning(true);
        startPolling();
    } catch (e) {
        appendLog('❌ Failed to restart: ' + e.message + '\n');
        setStatus('error', 'Error');
        setRunning(false);
        showEngineError('Failed to restart the translator: ' + e.message);
    } finally {
        startBtn.disabled = false;
        restartBtn.disabled = false;
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  ENGINE LOADING / ERROR OVERLAY
// ═══════════════════════════════════════════════════════════════════════════
function showEngineOverlay(title, message) {
    engineOverlay.classList.remove('error');
    engineOverlay.classList.add('visible');
    engineOverlayTitle.textContent = title;
    engineOverlayMessage.textContent = message;
    engineOverlayProgressBar.style.width = '0%';
    engineOverlayCancelBtn.textContent = 'Cancel';
    engineOverlayRetryBtn.classList.add('hidden');
}

function updateEngineOverlay(message) {
    if (!engineOverlay.classList.contains('visible') || engineOverlay.classList.contains('error')) return;
    engineOverlayMessage.textContent = message;
}

function updateEngineOverlayProgress(value) {
    if (!engineOverlay.classList.contains('visible') || engineOverlay.classList.contains('error')) return;
    engineOverlayProgressBar.style.width = (value * 100) + '%';
}

function showEngineError(message) {
    engineOverlay.classList.add('visible', 'error');
    engineOverlayTitle.textContent = 'Couldn\'t start the translator';
    engineOverlayMessage.textContent = message;
    engineOverlayCancelBtn.textContent = 'Dismiss';
    engineOverlayRetryBtn.classList.remove('hidden');
}

function hideEngineOverlay() {
    engineOverlay.classList.remove('visible', 'error');
}

function setSettingsDirty(dirty) {
    settingsDirty = dirty && isRunning;
    restartBanner.classList.toggle('visible', settingsDirty);
}

function onSettingsChanged() {
    const key = JSON.stringify(gatherSettings());
    saveBtn.disabled = (key === savedSettingsKey);
    if (isRunning) {
        setSettingsDirty(key !== appliedSettingsKey);
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  POLLING (fetch messages from Python queue)
// ═══════════════════════════════════════════════════════════════════════════
function startPolling() {
    if (pollInterval) return;
    pollInterval = setInterval(pollMessages, 200);
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

async function pollMessages() {
    try {
        const messages = await pywebview.api.poll_messages();
        if (!messages || messages.length === 0) return;

        messages.forEach(msg => {
            switch (msg.type) {
                case 'log':
                    appendLog(msg.text);
                    break;
                case 'subtitle':
                    addTranslation(msg);
                    break;
                case 'progress':
                    updateEngineOverlayProgress(msg.value);
                    break;
                case 'status':
                    setStatus(msg.state, msg.text);
                    updateEngineOverlay(msg.text);
                    if (msg.state === 'running') {
                        hideEngineOverlay();
                    }
                    break;
                case 'error':
                    showEngineError(msg.text);
                    break;
                case 'channel_status':
                    setChannelStatus(msg.channel, msg.state, msg.text);
                    break;
                case 'stopped':
                    setStatus('idle', 'Ready');
                    setRunning(false);
                    // Keep the overlay up if it's showing an error so the
                    // user can read it and hit Retry, instead of it
                    // vanishing the instant the engine thread exits.
                    if (!engineOverlay.classList.contains('error')) {
                        hideEngineOverlay();
                    }
                    resetChannelStatuses();
                    stopPolling();
                    break;
            }
        });
    } catch (e) {
        // Ignore polling errors
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  UI HELPERS
// ═══════════════════════════════════════════════════════════════════════════
function setStatus(state, text) {
    statusDot.className = 'status-dot ' + state;
    statusText.textContent = text;
}

const CHANNEL_STATUS_LABELS = {
    listening: 'Listening',
    failed: 'Failed',
    disabled: 'Disabled',
    idle: 'Not started',
};

function setChannelStatus(channel, state, detail) {
    const el = channel === 'loopback' ? lbChannelStatus : micChannelStatus;
    el.className = 'channel-status ' + state;
    el.querySelector('.channel-status-text').textContent = CHANNEL_STATUS_LABELS[state] || state;
    el.title = detail || '';
}

function resetChannelStatuses() {
    setChannelStatus('mic', 'idle');
    setChannelStatus('loopback', 'idle');
}

function setRunning(running) {
    isRunning = running;
    if (running) {
        startBtn.classList.add('running');
        startBtn.querySelector('.btn-start-icon').textContent = '■';
        startBtn.querySelector('.btn-start-text').textContent = 'Stop Translator';
    } else {
        startBtn.classList.remove('running');
        startBtn.querySelector('.btn-start-icon').textContent = '▶';
        startBtn.querySelector('.btn-start-text').textContent = 'Start Translator';
        setSettingsDirty(false);
    }
}

function appendLog(text) {
    logText.textContent += text;
    // Auto-scroll log
    const logContent = $('logContent');
    logContent.scrollTop = logContent.scrollHeight;
}

function addTranslation(msg) {
    // Route to correct panel
    const isLoopback = msg.channel === 'loopback';
    const container = isLoopback ? lbMessages : micMessages;
    const welcome = isLoopback ? lbWelcome : micWelcome;
    const scroll = isLoopback ? lbOutputScroll : micOutputScroll;

    welcome.classList.add('hidden');

    const item = document.createElement('div');
    item.className = 'msg-item';

    const langInfo = `${msg.src_lang} → ${msg.tgt_lang}`;

    // When Whisper translates directly (e.g. Hindi→English), both
    // original and translated are the same English text. Skip the duplicate.
    const showOriginal = msg.original && msg.translated &&
        msg.original.trim() !== msg.translated.trim();

    item.innerHTML = `
        <div class="msg-channel">${langInfo}</div>
        ${showOriginal ? `<div class="msg-original">${escapeHtml(msg.original)}</div>` : ''}
        <div class="msg-translated">${escapeHtml(msg.translated)}</div>
    `;

    container.appendChild(item);

    // Keep max 50 messages per panel
    while (container.children.length > 50) {
        container.removeChild(container.firstChild);
    }

    // Auto-scroll
    scroll.scrollTop = scroll.scrollHeight;

    // Record for the Download Transcript button — kept in full, unlike the
    // on-screen panels which trim to 50 items each.
    transcriptLog.push({
        time: new Date(),
        channel: isLoopback ? 'Remote' : 'You',
        srcLang: msg.src_lang,
        tgtLang: msg.tgt_lang,
        original: showOriginal ? msg.original : '',
        translated: msg.translated,
    });
    downloadTranscriptBtn.disabled = false;
    downloadTranscriptBtn.title = 'Download transcript';
    transcriptCount.textContent = transcriptLog.length;
}

function downloadTranscript() {
    if (transcriptLog.length === 0) return;

    const pad = n => String(n).padStart(2, '0');
    const fmtTime = d => `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    const fmtStamp = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}_${pad(d.getHours())}-${pad(d.getMinutes())}-${pad(d.getSeconds())}`;

    const now = new Date();
    const lines = [
        `Voxxwire Transcript`,
        `Generated: ${now.toLocaleString()}`,
        '',
    ];
    transcriptLog.forEach(entry => {
        lines.push(`[${fmtTime(entry.time)}] ${entry.channel} (${entry.srcLang} → ${entry.tgtLang})`);
        if (entry.original) lines.push(`  ${entry.original}`);
        lines.push(`  → ${entry.translated}`);
        lines.push('');
    });

    const content = lines.join('\n');
    const filename = `voxxwire_transcript_${fmtStamp(now)}.txt`;

    pywebview.api.download_transcript(content, filename).then(saved => {
        if (saved) {
            appendLog('⬇ Transcript saved.\n');
        }
    }).catch(e => {
        appendLog('❌ Failed to save transcript: ' + e.message + '\n');
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ═══════════════════════════════════════════════════════════════════════════
//  PROTOTYPE BANNER DISMISS
// ═══════════════════════════════════════════════════════════════════════════
const prototypeBannerClose = $('prototypeBannerClose');
const prototypeBanner = $('prototypeBanner');

if (prototypeBannerClose && prototypeBanner) {
    prototypeBannerClose.addEventListener('click', () => {
        prototypeBanner.classList.add('hidden');
    });
}
