/* ═══════════════════════════════════════════════════════════════════════════
   Voxxwire — Shared GitHub Releases helpers
   Used by index.html (preview) and releases.html (full changelog)
   ═══════════════════════════════════════════════════════════════════════════ */

const GITHUB_REPO = 'raj20023/voxxwire';

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// Minimal, safe markdown-lite renderer for GitHub release notes.
// Input is HTML-escaped first, so no injected tag can survive.
function renderMarkdown(md) {
    let html = escapeHtml(md || '_No description provided._');
    // GitHub release bodies use CRLF line endings. Normalize to LF — in JS
    // (unlike most other regex engines) a bare "." excludes "\r" as well as
    // "\n", so leftover CR characters silently break every line-based regex below.
    html = html.replace(/\r\n?/g, '\n');

    html = html.replace(/```([\s\S]*?)```/g, (_, code) => `<pre><code>${code.trim()}</code></pre>`);
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/(?<!\*)\*(?!\*)([^*]+)\*(?!\*)/g, '<em>$1</em>');
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    html = html.replace(/^#{1,3}\s+(.*)$/gm, '<h4>$1</h4>');
    html = html.replace(/^(?:-{3,}|\*{3,})$/gm, '<hr>');
    html = html.replace(/^&gt;\s?(.*)$/gm, '<blockquote>$1</blockquote>');

    html = html.replace(/(^|\n)((?:[-*]\s+.*(?:\n|$))+)/g, (_, pre, list) => {
        const items = list.trim().split('\n').map(l => `<li>${l.replace(/^[-*]\s+/, '')}</li>`).join('');
        return `${pre}<ul>${items}</ul>`;
    });

    html = html.split(/\n{2,}/).map(block => {
        const trimmed = block.trim();
        if (!trimmed) return '';
        if (/^<(h4|ul|pre|hr|blockquote)/.test(trimmed)) return trimmed;
        return `<p>${trimmed.replace(/\n/g, '<br>')}</p>`;
    }).join('');

    return html;
}

function formatReleaseDate(iso) {
    return new Date(iso).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
}

function formatBytes(bytes) {
    if (!bytes) return '';
    const mb = bytes / (1024 * 1024);
    return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`;
}

async function fetchGithubReleases() {
    const res = await fetch(`https://api.github.com/repos/${GITHUB_REPO}/releases`, {
        headers: { 'Accept': 'application/vnd.github.v3+json' }
    });
    if (!res.ok) throw new Error(`GitHub API responded ${res.status}`);
    return res.json();
}

function findLatestStable(releases) {
    return releases.find(r => !r.draft && !r.prerelease);
}

function renderReleaseAssets(assets) {
    if (!assets || assets.length === 0) return '';
    return `<div class="release-assets">${assets.map(a => `
        <a class="release-asset-link" href="${a.browser_download_url}" target="_blank" rel="noopener noreferrer">
            ⬇ ${escapeHtml(a.name)} · ${formatBytes(a.size)}
        </a>`).join('')}</div>`;
}
