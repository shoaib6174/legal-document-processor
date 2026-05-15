const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');
const uploadResult = document.getElementById('uploadResult');
const visualizationSection = document.getElementById('visualizationSection');
const pdfPages = document.getElementById('pdfPages');
const statsBar = document.getElementById('statsBar');
const entityLegend = document.getElementById('entityLegend');
const highlightedText = document.getElementById('highlightedText');
const entitiesTable = document.getElementById('entitiesTable').querySelector('tbody');
const generateSection = document.getElementById('generateSection');
const generateBtn = document.getElementById('generateBtn');
const evidenceSection = document.getElementById('evidenceSection');
const evidenceList = document.getElementById('evidenceList');
const draftSection = document.getElementById('draftSection');
const draftEditor = document.getElementById('draftEditor');
const submitEditBtn = document.getElementById('submitEditBtn');
const feedbackResult = document.getElementById('feedbackResult');

let currentDraft = null;
let currentDocId = null;

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

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function renderHighlightedText(rawText, entities) {
    // Sort by start position descending to avoid offset shifts during replacement
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

function renderStatsBar(data) {
    statsBar.innerHTML = `
        <div class="stat-item">
            <div class="stat-value">${data.pages}</div>
            <div class="stat-label">Pages</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">${data.chunks}</div>
            <div class="stat-label">Chunks</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">${data.entities.length}</div>
            <div class="stat-label">Entities</div>
        </div>
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

async function handleFile(file) {
    const formData = new FormData();
    formData.append('file', file);

    uploadResult.innerHTML = '<p>Uploading and processing...</p>';

    const res = await fetch('/upload', { method: 'POST', body: formData });
    const data = await res.json();

    currentDocId = data.filename;

    // Show upload summary
    uploadResult.innerHTML = `
        <p><strong>Uploaded:</strong> ${data.filename}</p>
        <p>${data.pages} pages | ${data.chunks} chunks | ${data.entities.length} entities</p>
    `;

    // Show visualization
    visualizationSection.classList.remove('hidden');
    renderPdfPages(data.filename, data.pages);
    renderStatsBar(data);
    renderEntityLegend(data.entities);
    highlightedText.innerHTML = renderHighlightedText(data.raw_text, data.entities);
    renderEntitiesTable(data.entities);

    generateSection.classList.remove('hidden');
}

// Generate
generateBtn.addEventListener('click', async () => {
    generateBtn.disabled = true;
    generateBtn.textContent = 'Generating...';

    const formData = new FormData();
    formData.append('query', 'Generate a case fact summary');

    const res = await fetch('/generate', { method: 'POST', body: formData });
    const data = await res.json();

    currentDraft = data.draft;

    // Show evidence
    evidenceSection.classList.remove('hidden');
    evidenceList.innerHTML = data.evidence.map((e, i) => `
        <div class="evidence">
            <strong>[${i+1}] ${e.chunk_id}</strong> (score: ${e.score.toFixed(3)})<br>
            ${escapeHtml(e.text.substring(0, 300))}${e.text.length > 300 ? '...' : ''}
        </div>
    `).join('');

    // Show draft editor
    draftSection.classList.remove('hidden');
    draftEditor.value = JSON.stringify(data.draft, null, 2);

    // Show applied rules
    if (data.rules_applied.length > 0) {
        draftSection.insertAdjacentHTML('afterbegin', `
            <div style="background:#e8f5e9;padding:10px;margin-bottom:10px;border-radius:4px;">
                <strong>Applied correction rules:</strong>
                <ul>${data.rules_applied.map(r => `<li>${escapeHtml(r)}</li>`).join('')}</ul>
            </div>
        `);
    }

    generateBtn.disabled = false;
    generateBtn.textContent = 'Regenerate';
});

// Submit edits
submitEditBtn.addEventListener('click', async () => {
    try {
        const edited = JSON.parse(draftEditor.value);
        const formData = new FormData();
        formData.append('edited_draft', JSON.stringify(edited));

        submitEditBtn.disabled = true;
        const res = await fetch('/feedback', { method: 'POST', body: formData });
        const data = await res.json();

        feedbackResult.innerHTML = `
            <div style="background:#e8f5e9;padding:10px;border-radius:4px;">
                <strong>Feedback captured!</strong><br>
                Rules learned: ${data.rules_learned}<br>
                Active rules:<br>
                <ul>${data.active_rules.map(r => `<li>${escapeHtml(r)}</li>`).join('')}</ul>
            </div>
        `;
        submitEditBtn.disabled = false;
    } catch (e) {
        feedbackResult.innerHTML = `<div style="color:red;">Invalid JSON: ${escapeHtml(e.message)}</div>`;
    }
});
