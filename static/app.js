const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');
const uploadResult = document.getElementById('uploadResult');
const generateSection = document.getElementById('generateSection');
const generateBtn = document.getElementById('generateBtn');
const evidenceSection = document.getElementById('evidenceSection');
const evidenceList = document.getElementById('evidenceList');
const draftSection = document.getElementById('draftSection');
const draftEditor = document.getElementById('draftEditor');
const submitEditBtn = document.getElementById('submitEditBtn');
const feedbackResult = document.getElementById('feedbackResult');

let currentDraft = null;

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

async function handleFile(file) {
    const formData = new FormData();
    formData.append('file', file);

    uploadResult.innerHTML = 'Uploading...';
    const res = await fetch('/upload', { method: 'POST', body: formData });
    const data = await res.json();

    uploadResult.innerHTML = `
        <p><strong>Uploaded:</strong> ${data.filename}</p>
        <p>Chunks: ${data.chunks} | Entities: ${data.entities.length}</p>
        <pre>${JSON.stringify(data.entities, null, 2)}</pre>
    `;
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
            ${e.text}
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
                <ul>${data.rules_applied.map(r => `<li>${r}</li>`).join('')}</ul>
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
                <ul>${data.active_rules.map(r => `<li>${r}</li>`).join('')}</ul>
            </div>
        `;
        submitEditBtn.disabled = false;
    } catch (e) {
        feedbackResult.innerHTML = `<div style="color:red;">Invalid JSON: ${e.message}</div>`;
    }
});
