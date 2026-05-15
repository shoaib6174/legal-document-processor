const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');
const uploadResult = document.getElementById('uploadResult');
const visualizationSection = document.getElementById('visualizationSection');
const pdfPages = document.getElementById('pdfPages');
const statsBar = document.getElementById('statsBar');
const entityLegend = document.getElementById('entityLegend');
const entityBadges = document.getElementById('entityBadges');
const highlightedText = document.getElementById('highlightedText');
const entitiesTable = document.getElementById('entitiesTable').querySelector('tbody');
const chunksPanel = document.getElementById('chunksPanel');
const draftSection = document.getElementById('draftSection');
const draftLoading = document.getElementById('draftLoading');
const draftContent = document.getElementById('draftContent');
const draftEditor = document.getElementById('draftEditor');
const submitEditBtn = document.getElementById('submitEditBtn');
const feedbackResult = document.getElementById('feedbackResult');
const renderedDraft = document.getElementById('renderedDraft');
const feedbackSection = document.getElementById('feedbackSection');
const chunkModal = document.getElementById('chunkModal');
const modalClose = document.getElementById('modalClose');
const modalTitle = document.getElementById('modalTitle');
const modalMeta = document.getElementById('modalMeta');
const modalText = document.getElementById('modalText');

let currentDraft = null;
let currentDraftRaw = null;
let currentDocId = null;
let currentChunks = [];
let currentEvidence = [];

const ENTITY_COLORS = {
    date: { bg: '#e3f2fd', text: '#1565c0', label: 'Date' },
    amount: { bg: '#e8f5e9', text: '#2e7d32', label: 'Amount' },
    party: { bg: '#fff3e0', text: '#ef6c00', label: 'Party' },
    case_number: { bg: '#f3e5f5', text: '#6a1b9a', label: 'Case #' }
};

// Upload
dropzone.addEventListener('click', () => fileInput.click());
dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', (e) => {
    if (e.target.files.length) handleFile(e.target.files[0]);
});

// Panel tabs
document.querySelectorAll('.panel-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.panel-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        document.querySelectorAll('.tab-content').forEach(c => c.classList.add('hidden'));
        document.getElementById('tab' + tab.dataset.tab.charAt(0).toUpperCase() + tab.dataset.tab.slice(1)).classList.remove('hidden');
    });
});

// Modal
modalClose.addEventListener('click', () => chunkModal.classList.remove('visible'));
chunkModal.addEventListener('click', (e) => {
    if (e.target === chunkModal) chunkModal.classList.remove('visible');
});

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function renderHighlightedText(rawText, entities) {
    const sorted = [...entities].sort((a, b) => b.start - a.start);
    let html = escapeHtml(rawText);
    for (const e of sorted) {
        const span = `<span class="entity-${e.type}" title="${e.type}: ${escapeHtml(e.value)}">${escapeHtml(e.value)}</span>`;
        html = html.slice(0, e.start) + span + html.slice(e.end);
    }
    return html;
}

function renderPdfPages(docId, pageCount) {
    pdfPages.innerHTML = '';
    for (let i = 1; i <= pageCount; i++) {
        const pageDiv = document.createElement('div');
        pageDiv.className = 'pdf-page';
        pageDiv.innerHTML = `
            <img src="/rendered/${encodeURIComponent(docId)}/page_${i}.png" alt="Page ${i}" loading="lazy">
            <div class="pdf-page-label">Page ${i} of ${pageCount}</div>
        `;
        pdfPages.appendChild(pageDiv);
    }
}

function renderEntityLegend(entities) {
    const types = [...new Set(entities.map(e => e.type))];
    entityLegend.innerHTML = types.map(type => {
        const info = ENTITY_COLORS[type] || { label: type, bg: '#eee', text: '#333' };
        return `
            <div class="legend-item">
                <div class="legend-swatch" style="background:${info.bg};border-color:${info.text}33"></div>
                <span style="color:${info.text}">${info.label}</span>
            </div>
        `;
    }).join('');
}

function renderEntityBadges(entities) {
    entityBadges.innerHTML = entities.map(e => {
        const info = ENTITY_COLORS[e.type] || { bg: '#eee', text: '#333' };
        return `
            <span class="entity-badge" style="background:${info.bg};color:${info.text};border:1px solid ${info.text}33">
                <span class="badge-dot" style="background:${info.text}"></span>
                ${escapeHtml(e.value)}
            </span>
        `;
    }).join('');
}

function renderStatsBar(data) {
    statsBar.innerHTML = `
        <div class="stat-item"><div class="stat-value">${data.pages}</div><div class="stat-label">Pages</div></div>
        <div class="stat-item"><div class="stat-value">${data.chunks}</div><div class="stat-label">Chunks</div></div>
        <div class="stat-item"><div class="stat-value">${data.entities.length}</div><div class="stat-label">Entities</div></div>
    `;
}

function renderEntitiesTable(entities) {
    entitiesTable.innerHTML = entities.map(e => {
        const info = ENTITY_COLORS[e.type] || { label: e.type };
        return `
            <tr>
                <td><span class="entity-tag tag-${e.type}">${info.label}</span></td>
                <td>${escapeHtml(e.value)}</td>
                <td>${e.start}-${e.end}</td>
            </tr>
        `;
    }).join('');
}

function renderChunks(chunks) {
    chunksPanel.innerHTML = chunks.map(chunk => {
        const confClass = chunk.confidence_score >= 0.9 ? 'chunk-confidence-high' :
                          chunk.confidence_score >= 0.7 ? 'chunk-confidence-medium' : 'chunk-confidence-low';
        const confLabel = chunk.confidence_score >= 0.9 ? 'HIGH' :
                          chunk.confidence_score >= 0.7 ? 'MEDIUM' : 'LOW';
        return `
            <div class="chunk-card" data-chunk-id="${chunk.chunk_id}">
                <div class="chunk-header">
                    <span class="chunk-id">${chunk.chunk_id}</span>
                    <span class="chunk-meta">page ${chunk.page_num} · <span class="${confClass}">${confLabel}</span></span>
                </div>
                <div class="chunk-text">${escapeHtml(chunk.text)}</div>
            </div>
        `;
    }).join('');
}

function showChunkModal(chunkId) {
    const chunk = currentChunks.find(c => c.chunk_id === chunkId);
    const evidence = currentEvidence.find(e => e.chunk_id === chunkId);
    const source = chunk || evidence;
    if (!source) return;

    modalTitle.textContent = source.chunk_id;
    modalMeta.innerHTML = `
        <span>Page ${source.page_num}</span>
        ${source.confidence_score !== undefined ? `<span>Confidence: ${(source.confidence_score * 100).toFixed(0)}%</span>` : ''}
        ${source.score !== undefined ? `<span>Relevance: ${source.score.toFixed(3)}</span>` : ''}
    `;
    modalText.innerHTML = `<p style="white-space:pre-wrap;font-family:'SF Mono',Monaco,monospace;font-size:13px;line-height:1.7">${escapeHtml(source.text)}</p>`;
    chunkModal.classList.add('visible');
}

function highlightChunkCard(chunkId) {
    document.querySelectorAll('.chunk-card').forEach(c => c.classList.remove('highlighted'));
    const card = document.querySelector(`.chunk-card[data-chunk-id="${chunkId}"]`);
    if (card) {
        card.classList.add('highlighted');
        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

function wireCitations() {
    renderedDraft.querySelectorAll('.citation').forEach(el => {
        el.addEventListener('click', () => {
            const chunkId = el.textContent.trim();
            showChunkModal(chunkId);
            // Also switch to chunks tab and highlight
            document.querySelectorAll('.panel-tab').forEach(t => t.classList.remove('active'));
            document.querySelector('.panel-tab[data-tab="chunks"]').classList.add('active');
            document.querySelectorAll('.tab-content').forEach(c => c.classList.add('hidden'));
            document.getElementById('tabChunks').classList.remove('hidden');
            highlightChunkCard(chunkId);
        });
    });
}

async function handleFile(file) {
    const formData = new FormData();
    formData.append('file', file);

    uploadResult.innerHTML = '<p>Uploading and processing...</p>';

    const res = await fetch('/upload', { method: 'POST', body: formData });
    const data = await res.json();

    currentDocId = data.filename;
    // Note: chunks aren't returned by upload endpoint, we'll need to store what we have
    // The upload endpoint doesn't return chunks. We need to either:
    // 1. Modify upload to return chunks
    // 2. Or reconstruct from raw_text

    uploadResult.innerHTML = `
        <p><strong>Uploaded:</strong> ${data.filename}</p>
        <p>${data.pages} pages | ${data.chunks} chunks | ${data.entities.length} entities</p>
    `;

    visualizationSection.classList.remove('hidden');
    renderPdfPages(data.filename, data.pages);
    renderStatsBar(data);
    renderEntityLegend(data.entities);
    renderEntityBadges(data.entities);
    highlightedText.innerHTML = renderHighlightedText(data.raw_text, data.entities);
    renderEntitiesTable(data.entities);

    // Chunks aren't returned by upload. Build minimal chunk data from what's available.
    // We'll update this properly after generate returns evidence.
    currentChunks = [];
    chunksPanel.innerHTML = '<p style="color:#999;font-size:13px;padding:10px;">Chunks will appear after summary generation.</p>';

    draftSection.classList.remove('hidden');
    draftLoading.classList.remove('hidden');
    draftContent.classList.add('hidden');

    // Auto-generate draft
    await generateDraft();
}

async function generateDraft() {
    draftLoading.classList.remove('hidden');
    draftContent.classList.add('hidden');

    const formData = new FormData();
    formData.append('query', 'Generate a case fact summary');

    try {
        const res = await fetch('/generate', { method: 'POST', body: formData });
        const data = await res.json();

        currentDraft = data.draft;
        currentDraftRaw = JSON.stringify(data.draft, null, 2);
        currentEvidence = data.evidence;

        // Build chunks from evidence for the chunks panel
        currentChunks = data.evidence.map(e => ({
            chunk_id: e.chunk_id,
            text: e.text,
            page_num: e.page_num,
            confidence_score: 1.0  // Evidence chunks are from processed doc
        }));
        renderChunks(currentChunks);

        // Render the readable HTML summary
        renderedDraft.innerHTML = data.draft_html || `<pre>${escapeHtml(JSON.stringify(data.draft, null, 2))}</pre>`;
        wireCitations();

        // Pre-populate JSON editor for feedback
        draftEditor.value = currentDraftRaw;

        // Show applied rules
        const existingRules = renderedDraft.querySelector('.rules-banner');
        if (existingRules) existingRules.remove();
        if (data.rules_applied.length > 0) {
            renderedDraft.insertAdjacentHTML('beforebegin', `
                <div class="rules-banner" style="background:#e8f5e9;padding:10px;margin-bottom:10px;border-radius:4px;">
                    <strong>Applied correction rules:</strong>
                    <ul>${data.rules_applied.map(r => `<li>${escapeHtml(r)}</li>`).join('')}</ul>
                </div>
            `);
        }

        // Show feedback section
        feedbackSection.classList.remove('hidden');
    } catch (err) {
        renderedDraft.innerHTML = `<div style="color:#c62828;padding:20px;">Error generating summary: ${escapeHtml(err.message)}</div>`;
    } finally {
        draftLoading.classList.add('hidden');
        draftContent.classList.remove('hidden');
    }
}

// Submit edits
submitEditBtn.addEventListener('click', async () => {
    try {
        const edited = JSON.parse(draftEditor.value);
        const formData = new FormData();
        formData.append('edited_draft', JSON.stringify(edited));

        submitEditBtn.disabled = true;
        const res = await fetch('/feedback', { method: 'POST', body: formData });
        const data = await res.json();

        const effText = data.effectiveness_pct !== null
            ? `<span style="color:#2e7d32;font-weight:600;">${data.effectiveness_pct}%</span> rule effectiveness`
            : `<span style="color:#666;">Not enough data yet</span>`;

        feedbackResult.innerHTML = `
            <div style="background:#e8f5e9;padding:12px;border-radius:4px;margin-top:10px;">
                <strong>Feedback captured!</strong><br>
                ${data.new_rules_learned} new rule(s) learned · ${data.total_diffs} change(s) detected<br>
                ${data.rules_scored > 0 ? `${data.rules_scored} previous rule(s) scored · ` : ''}${effText}<br>
                <strong>Active rules:</strong>
                <ul>${data.active_rules.map(r => `<li>${escapeHtml(r)}</li>`).join('')}</ul>
            </div>
        `;
        submitEditBtn.disabled = false;
    } catch (e) {
        feedbackResult.innerHTML = `<div style="color:red;">Invalid JSON: ${escapeHtml(e.message)}</div>`;
    }
});
