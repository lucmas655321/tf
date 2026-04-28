// [of]: root
// #tf:focus_user:root/ctx_menu
// #tf:focus_ai:root/wrap
// [of]: state
'use strict';

const vscode = acquireVsCodeApi();

let tree = null;
let path = [];     // ['root', 'architettura', 'backend']
let currentFile = '';  // path assoluto del file aperto in Miller

let editMode    = false;
let pendingSave = false;

let selectedChip    = null;
let chipClipboard   = [];   // { label, uid }[]
let savedRange      = null; // selezione salvata prima del click su Wrap

let _wrapChip      = null;   // span placeholder nel DOM
let _wrapText      = null;   // testo estratto (da mandare al backend)

let ctxNode = null;
let chipMenuTarget = null;

let _navigatingFromAI = false;
let _pendingFocusAI   = null;   // blockPath da applicare al prossimo tree update
let _pendingNavBack   = null;   // path[] da ripristinare al prossimo tree (back cross-file)
// [cf]
// [of]: helpers
function getNode(root, pathArr) {
    let node = root;
    for (const part of pathArr.slice(1)) {
        const child = (node.items || [])
            .filter(i => i.type === 'block')
            .find(i => i.label === part || i.uid === part);
        if (!child) { return null; }
        node = child;
    }
    return node;
}

function childBlocks(node) {
    return (node.items || []).filter(i => i.type === 'block');
}
// [cf]
// [of]: chip_clipboard
function selectChip(span) {
    if (selectedChip) { selectedChip.classList.remove('selected'); }
    selectedChip = span;
    if (span) { span.classList.add('selected'); }
}

function clearChipSelection() { selectChip(null); }

function insertChipAtRange(label, uid, range) {
    const div = document.getElementById('block-text');
    const item = { type: 'block', label, uid: uid || '', path: '', start_line: -1, items: [] };
    const chip = makeBlockChip(item);

    if (range && div.contains(range.commonAncestorContainer)) {
        range.deleteContents();
        range.insertNode(chip);
        range.setStartAfter(chip);
        range.collapse(true);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        return chip;
    }

    const sel = window.getSelection();
    if (sel && sel.rangeCount > 0) {
        const r = sel.getRangeAt(0);
        if (div.contains(r.commonAncestorContainer)) {
            r.deleteContents();
            r.insertNode(chip);
            r.setStartAfter(chip);
            r.collapse(true);
            sel.removeAllRanges();
            sel.addRange(r);
            return chip;
        }
    }

    div.appendChild(chip);
    return chip;
}

function insertChipAtCursor(label, uid) {
    return insertChipAtRange(label, uid, null);
}
// [cf]
// [of]: chip_dom
function makeBlockChip(item) {
    const span = document.createElement('span');
    span.className = 'block-ref';
    span.contentEditable = 'false';
    span.draggable = true;
    span.dataset.label = item.label;
    span.dataset.uid   = item.uid || '';
    span.textContent   = `[${item.label}]`;

    span.addEventListener('click', (e) => {
        e.stopPropagation();
        if (editMode) { selectChip(span); }
        else          { navigateTo(item); }
    });

    span.addEventListener('dblclick', (e) => {
        e.stopPropagation();
        if (!editMode) { return; }
        flattenChipInline(span, item);
    });

    span.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (editMode) { showChipMenu(e, span, item); }
    });

    span.addEventListener('dragstart', (e) => {
        if (!editMode) { e.preventDefault(); return; }
        selectChip(span);
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', `__chip__:${item.label}:${item.uid || ''}`);
        span.classList.add('dragging');
    });
    span.addEventListener('dragend', () => {
        span.classList.remove('dragging');
    });

    return span;
}
// [cf]
// [of]: flatten
function flattenChipInline(span, item) {
    const fragment = document.createDocumentFragment();

    for (const subItem of (item.items || [])) {
        if (subItem.type === 'text') {
            const lines = subItem.text.split('\n');
            for (const line of lines) {
                const row = document.createElement('div');
                row.appendChild(line ? document.createTextNode(line) : document.createElement('br'));
                fragment.appendChild(row);
            }
        } else {
            const row = document.createElement('div');
            row.appendChild(makeBlockChip(subItem));
            fragment.appendChild(row);
        }
    }

    const parentRow = span.closest('div');
    if (parentRow && parentRow !== document.getElementById('block-text')) {
        parentRow.parentNode.insertBefore(fragment, parentRow);
        parentRow.remove();
    } else {
        span.parentNode.insertBefore(fragment, span);
        span.remove();
    }
    clearChipSelection();
}
// [cf]
// [of]: chip_menu
function showChipMenu(e, span, item) {
    chipMenuTarget = { span, item };
    const menu = document.getElementById('chip-menu');
    menu.style.left = e.clientX + 'px';
    menu.style.top  = e.clientY + 'px';
    menu.classList.add('visible');
}

function hideChipMenu() {
    const menu = document.getElementById('chip-menu');
    if (menu) { menu.classList.remove('visible'); }
    chipMenuTarget = null;
}
// [cf]
// [of]: wrap
// [of]: wrapSelection
function wrapSelection() {
    if (!editMode) { return; }
    const div = document.getElementById('block-text');

    let range = savedRange;
    savedRange = null;
    if (!range) {
        const sel = window.getSelection();
        if (sel && !sel.isCollapsed && sel.rangeCount > 0) {
            range = sel.getRangeAt(0).cloneRange();
        }
    }
    if (!range || range.collapsed) { return; }
    if (!div.contains(range.commonAncestorContainer)) { return; }

    const fragment = range.cloneContents();
    const selectedText = serializeFragment(fragment);
    if (!selectedText.trim()) { return; }

    range.deleteContents();
    const placeholder = document.createElement('span');
    placeholder.className = 'block-ref';
    placeholder.contentEditable = 'false';
    placeholder.textContent = '[?]';
    placeholder.style.opacity = '0.5';
    range.insertNode(placeholder);
    window.getSelection().removeAllRanges();

    _wrapChip = placeholder;
    _wrapText = selectedText;

    showWrapInput(selectedText, placeholder);
}
// [cf]

// [of]: showWrapInput
function showWrapInput(selectedText, placeholder) {
    const bar = document.getElementById('save-bar');

    let inp = document.getElementById('wrap-input');
    if (!inp) {
        inp = document.createElement('input');
        inp.id = 'wrap-input';
        inp.type = 'text';
        inp.placeholder = 'Block name\u2026';
        inp.style.cssText = 'flex:1;padding:1px 6px;font-size:inherit;background:var(--vscode-input-background);color:var(--vscode-input-foreground);border:1px solid var(--vscode-focusBorder);outline:none;min-width:80px;max-width:160px';
        bar.insertBefore(inp, document.getElementById('btn-wrap'));
    }
    inp.value = '';
    inp.style.display = '';
    inp.focus();

    function cancel() {
        inp.style.display = 'none';
        inp.onkeydown = null;
        if (placeholder && placeholder.parentNode) {
            const textNode = document.createTextNode(selectedText);
            placeholder.parentNode.insertBefore(textNode, placeholder);
            placeholder.remove();
        }
        _wrapChip = null;
        _wrapText = null;
    }

    function commit() {
        const label = inp.value.trim();
        inp.style.display = 'none';
        inp.onkeydown = null;
        if (!label) { cancel(); return; }

        const current = getNode(tree, path);
        const tempItem = { type: 'block', label, uid: '', path: current.path + '/' + label, start_line: -1, items: [] };
        const chip = makeBlockChip(tempItem);
        if (placeholder && placeholder.parentNode) {
            placeholder.parentNode.insertBefore(chip, placeholder);
            placeholder.remove();
        }
        _wrapChip = null;

        const text = serializeEditDiv();
        editMode = false;
        const div = document.getElementById('block-text');
        div.contentEditable = 'false';
        div.classList.remove('edit-mode');
        document.getElementById('save-bar').classList.remove('visible');
        vscode.postMessage({
            type:      'editText',
            path:      current.path,
            text,
            newBlocks: { [label]: selectedText },
        });
    }

    inp.onkeydown = (e) => {
        if (e.key === 'Enter')  { e.preventDefault(); commit(); }
        if (e.key === 'Escape') { cancel(); }
    };
    setTimeout(() => {
        document.addEventListener('click', function outside(e) {
            if (e.target !== inp) { cancel(); document.removeEventListener('click', outside); }
        });
    }, 100);
}
// [cf]
// [cf]
// [of]: edit_mode
// [of]: enterEditMode
function enterEditMode() {
    if (editMode) { return; }
    const current = getNode(tree, path);
    if (!current) { console.error('enterEditMode: no current node'); return; }
    editMode = true;

    const div = document.getElementById('block-text');
    div.contentEditable = 'true';
    div.classList.add('edit-mode');

    div.innerHTML = '';
    const items = current.items || [];
    for (const it of items) {
        if (it.type === 'text') {
            const lines = it.text.split('\n');
            for (const line of lines) {
                const row = document.createElement('div');
                row.appendChild(line ? document.createTextNode(line) : document.createElement('br'));
                div.appendChild(row);
            }
        } else {
            const row = document.createElement('div');
            row.appendChild(makeBlockChip(it));
            div.appendChild(row);
        }
    }

    div.focus();
    const sel = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(div);
    range.collapse(false);
    sel.removeAllRanges();
    sel.addRange(range);

    document.getElementById('save-bar').classList.add('visible');
}
// [cf]

// [of]: serialize
function serializeRow(rowNode) {
    const parts = [];
    for (const child of rowNode.childNodes) {
        if (child.nodeType === Node.TEXT_NODE) {
            parts.push(child.textContent);
        } else if (child.nodeName === 'BR') {
            // riga vuota
        } else if (child.nodeType === Node.ELEMENT_NODE) {
            if (child.classList && child.classList.contains('block-ref')) {
                parts.push(`[${child.dataset.label}]`);
            } else {
                parts.push(child.textContent);
            }
        }
    }
    return parts.join('');
}

function serializeNodes(childNodes) {
    const lines = [];
    for (const child of childNodes) {
        if (child.nodeName === 'DIV') {
            lines.push(serializeRow(child));
        } else if (child.nodeType === Node.TEXT_NODE) {
            lines.push(child.textContent);
        } else if (child.nodeName === 'BR') {
            lines.push('');
        } else if (child.nodeType === Node.ELEMENT_NODE &&
                   child.classList && child.classList.contains('block-ref')) {
            lines.push(`[${child.dataset.label}]`);
        }
    }
    return lines.join('\n');
}

function serializeFragment(frag) { return serializeNodes(frag.childNodes); }
function serializeEditDiv() { return serializeNodes(document.getElementById('block-text').childNodes); }
// [cf]

// [of]: exitEditMode
function exitEditMode(save) {
    if (!editMode) { return; }

    clearChipSelection();
    document.getElementById('save-bar').classList.remove('visible');

    if (save) {
        const current = getNode(tree, path);
        if (!current) {
            editMode = false;
            const div = document.getElementById('block-text');
            div.contentEditable = 'false';
            div.classList.remove('edit-mode');
            renderContent();
            return;
        }
        const text = serializeEditDiv();
        pendingSave = true;
        editMode = false;
        const div = document.getElementById('block-text');
        div.contentEditable = 'false';
        div.classList.remove('edit-mode');
        vscode.postMessage({ type: 'editText', path: current.path, text });
    } else {
        editMode = false;
        const div = document.getElementById('block-text');
        div.contentEditable = 'false';
        div.classList.remove('edit-mode');
        renderContent();
    }
}
// [cf]

function saveText()    { exitEditMode(true); }
function discardText() { exitEditMode(false); }
// [cf]
// [of]: rendering
// [of]: makeCol
function makeCol(nodes, selectedPath) {
    const col = document.createElement('div');
    col.className = 'col';
    for (const node of nodes) {
        const item = document.createElement('div');
        item.className = 'col-item';
        item.dataset.path = node.path;
        item.dataset.line = String(node.start_line);
        if (childBlocks(node).length > 0) { item.classList.add('has-children'); }
        if (node.path.replace(/@\d+/g, '') === selectedPath) { item.classList.add('selected'); }
        if (node.notes && node.notes.length > 0) { item.classList.add('has-notes'); }

        const labelSpan = document.createElement('span');
        labelSpan.textContent = node.label;
        item.appendChild(labelSpan);
        if (node.notes && node.notes.length > 0) {
            const badge = document.createElement('span');
            badge.className = 'note-badge';
            badge.textContent = '\uD83D\uDCCC';
            badge.title = node.notes.join('\n');
            item.appendChild(badge);
        }

        item.addEventListener('click', () => userNavigateTo(node));
        item.addEventListener('contextmenu', (e) => showCtxMenu(e, node));
        col.appendChild(item);
    }
    return col;
}
// [cf]
// [of]: renderColumns
function renderColumns() {
    const container = document.getElementById('columns');
    container.innerHTML = '';

    // col -1: chip root@nomefile (+ back chip se c'è history)
    const rootCol = document.createElement('div');
    rootCol.className = 'col';

    // back chip: compare sopra root@nomefile quando c'è history cross-file
    if (navHistory.length > 0) {
        const prev = navHistory[navHistory.length - 1];
        const prevFile  = prev.file.split('/').pop();
        const prevBlock = prev.path.slice(1).join('/') || 'root';
        const backChip = document.createElement('div');
        backChip.className = 'col-item back-chip';
        backChip.textContent = '\u2190 ' + prevFile + (prevBlock !== 'root' ? '@' + prevBlock : '');
        backChip.title = 'Back to ' + prev.file + '@' + prev.path.join('/') + ' (Ctrl+Backspace)';
        backChip.addEventListener('click', () => navigateHistoryBack());
        rootCol.appendChild(backChip);
    }

    const rootChip = document.createElement('div');
    rootChip.className = 'col-item' + (path.length === 1 ? ' selected' : '');
    const fileName = currentFile ? currentFile.split('/').pop() : 'root';
    rootChip.textContent = 'root@' + fileName;
    rootChip.title = currentFile || 'root';
    rootChip.addEventListener('click', () => navigateToRoot());
    rootCol.appendChild(rootChip);
    container.appendChild(rootCol);

    // col 0: figli diretti di root
    const rootChildren = childBlocks(tree);
    const col0Selected = path.length >= 2 ? path.slice(0, 2).join('/') : null;
    container.appendChild(makeCol(rootChildren, col0Selected));

    // col 1..N: figli del nodo selezionato ad ogni livello
    for (let depth = 1; depth < path.length; depth++) {
        const parentNode = getNode(tree, path.slice(0, depth + 1));
        if (!parentNode) { break; }
        const items = childBlocks(parentNode);
        if (items.length === 0) { break; }

        const selectedPath = depth + 1 < path.length
            ? path.slice(0, depth + 2).join('/')
            : null;

        container.appendChild(makeCol(items, selectedPath));
    }
}
// [cf]
// [of]: renderNavHistory
function renderNavHistory() {
    const bar = document.getElementById('nav-history-bar');
    if (!bar) { return; }
    bar.innerHTML = '';
    if (navHistory.length === 0) { return; }
    navHistory.forEach((entry, i) => {
        const chip = document.createElement('span');
        chip.className = 'nav-hist-chip';
        const fname = entry.file.split('/').pop() ?? entry.file;
        const bpath = entry.path.slice(1).join('/') || 'root';  // salta 'root' iniziale
        chip.textContent = fname + (bpath !== 'root' ? ' › ' + bpath : '');
        chip.title = entry.file + '@' + entry.path.join('/');
        chip.addEventListener('click', () => {
            // naviga direttamente a questo punto della history (taglia gli entry dopo)
            navHistory.splice(i);
            const target = entry.file + '@' + entry.path.join('/');
            if (entry.file === currentFile) {
                path = entry.path;
                renderColumns();
                renderContent();
            } else {
                _pendingNavBack = entry.path;
                vscode.postMessage({ type: 'openRef', target });
            }
            renderNavHistory();
        });
        bar.appendChild(chip);
    });
    // separatore finale → posizione corrente
    const sep = document.createElement('span');
    sep.className = 'nav-hist-sep';
    sep.textContent = ' › ';
    bar.appendChild(sep);
    const cur = document.createElement('span');
    cur.className = 'nav-hist-current';
    const cfname = currentFile.split('/').pop() ?? currentFile;
    const cpath  = path.slice(1).join('/') || 'root';
    cur.textContent = cfname + (cpath !== 'root' ? ' › ' + cpath : '');
    bar.appendChild(cur);
}
// [cf]
// [of]: renderContent
function renderContent() {
    const current = getNode(tree, path);
    if (!current) { return; }

    renderNavHistory();

    document.getElementById('block-header').innerHTML =
        `<span>${current.label}</span><span class="path">${current.path}</span>`;

    const div = document.getElementById('block-text');
    div.contentEditable = 'false';
    div.classList.remove('edit-mode');
    div.innerHTML = '';

    if (current.notes && current.notes.length > 0) {
        const noteBar = document.createElement('div');
        noteBar.className = 'note-bar';
        noteBar.innerHTML = current.notes.map(n =>
            `<div class="note-item">\uD83D\uDCCC ${n}</div>`
        ).join('');
        div.appendChild(noteBar);
    }

    // tf:ref — chip cliccabili per navigazione cross-file
    if (current.refs && current.refs.length > 0) {
        const refBar = document.createElement('div');
        refBar.className = 'ref-bar';
        for (const ref of current.refs) {
            const chip = document.createElement('span');
            chip.className = 'ref-chip';
            chip.textContent = '\uD83D\uDD17 ' + ref;
            chip.title = 'Ctrl+click per tornare indietro';
            chip.addEventListener('click', (e) => navigateRef(ref, e.ctrlKey));
            refBar.appendChild(chip);
        }
        div.appendChild(refBar);
    }

    const lang = getLanguageFromPath(currentFile);
    const codeEls = [];
    let textBuf = [];
    for (const item of (current.items || [])) {
        if (item.type === 'note') { continue; }
        if (item.type === 'text') {
            textBuf.push(item.text);
        } else {
            if (textBuf.length > 0) {
                const pre = document.createElement('pre');
                pre.className = 'miller-code';
                const code = document.createElement('code');
                code.className = 'language-' + lang;
                code.textContent = textBuf.join('\n');
                pre.appendChild(code);
                div.appendChild(pre);
                codeEls.push(code);
                textBuf = [];
            }
            const span = document.createElement('span');
            span.className = 'child-ref';
            span.textContent = `  \u2192 ${item.label}`;
            span.dataset.uid  = item.uid;
            span.dataset.path = item.path;
            span.addEventListener('click', () => navigateTo(item));
            div.appendChild(span);
            div.appendChild(document.createTextNode('\n'));
        }
    }
    if (textBuf.length > 0) {
        const pre = document.createElement('pre');
        pre.className = 'miller-code';
        const code = document.createElement('code');
        code.className = 'language-' + lang;
        code.textContent = textBuf.join('\n');
        pre.appendChild(code);
        div.appendChild(pre);
        codeEls.push(code);
    }
    // Highlighting differito: non blocca l'event loop né il server RPC
    if (codeEls.length > 0 && typeof Prism !== 'undefined' && Prism.languages[lang]) {
        requestAnimationFrame(() => {
            for (const code of codeEls) { Prism.highlightElement(code); }
        });
    }
}
// [cf]
// [of]: getLanguageFromPath
function getLanguageFromPath(filePath) {
    if (!filePath) { return 'none'; }
    const ext = filePath.split('.').pop().toLowerCase();
    const map = { py: 'python', ts: 'typescript', js: 'javascript', css: 'css', md: 'markdown' };
    return map[ext] || 'none';
}
// [cf]
// [cf]
// [of]: navigation
// Stack history per navigazione cross-file (Ctrl+Back)
let navHistory = [];  // [{file, path}]

function navigateTo(node) {
    if (editMode) { exitEditMode(false); }
    path = node.path.replace(/@\d+/g, '').split('/');
    renderColumns();
    renderContent();

    if (node.start_line >= 0) {
        vscode.postMessage({ type: 'revealLine', line: node.start_line + 1 });
    }
}

// Navigazione utente (click o tastiera) — aggiorna anche focus_user per l'AI
function userNavigateTo(node) {
    navigateTo(node);
    const cleanPath = node.path.replace(/@\d+/g, '');
    vscode.postMessage({ type: 'setFocusUser', file: currentFile, path: cleanPath });
}

// Salto cross-file via tf:ref — salva posizione corrente nello stack
function navigateRef(target, ctrlKey) {
    if (ctrlKey && navHistory.length > 0) {
        navigateHistoryBack();
        return;
    }
    navHistory.push({ file: currentFile, path: path.slice() });
    renderNavHistory();
    vscode.postMessage({ type: 'openRef', target });
}

// Torna al caller precedente (Ctrl+Backspace)
function navigateHistoryBack() {
    const prev = navHistory.pop();
    if (!prev) { return; }
    renderNavHistory();
    if (prev.file === currentFile) {
        path = prev.path;
        renderColumns();
        renderContent();
        vscode.postMessage({ type: 'setFocusUser', file: currentFile, path: prev.path.join('/') });
    } else {
        _pendingNavBack = prev.path;
        vscode.postMessage({ type: 'openRef', target: prev.file + '@' + prev.path.join('/') });
    }
}

function navigateToRoot() {
    if (editMode) { exitEditMode(false); }
    path = ['root'];
    renderColumns();
    renderContent();
    vscode.postMessage({ type: 'setFocusUser', file: currentFile, path: 'root' });
}

function navigateBack() {
    if (editMode) { exitEditMode(false); }
    if (path.length > 2) {
        path = path.slice(0, -1);
        renderColumns();
        renderContent();
    } else if (path.length === 2) {
        navigateToRoot();
    }
}

function navigateSibling(delta) {
    if (editMode) { return; }
    const parent = getNode(tree, path.slice(0, -1));
    if (!parent) { return; }
    const siblings = childBlocks(parent);
    const currentLabel = path[path.length - 1].split('@')[0];
    const idx = siblings.findIndex(n => n.label === currentLabel);
    if (idx < 0) { return; }
    const next = siblings[idx + delta];
    if (next) { userNavigateTo(next); }
}
// [cf]
// [of]: propose_mode
// ---------------------------------------------------------------------------
// Propose mode — mostra diff proposto dall'AI, attende Apply/Discard
// ---------------------------------------------------------------------------

let _proposePending = null;   // { text, newBlocks, resolve, hasChanges }

function diffLines(oldText, newText) {
    const oldLines = oldText === '' ? [] : oldText.split('\n');
    const newLines = newText === '' ? [] : newText.split('\n');
    const m = oldLines.length, n = newLines.length;
    const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
    for (let i = m - 1; i >= 0; i--) {
        for (let j = n - 1; j >= 0; j--) {
            dp[i][j] = oldLines[i] === newLines[j]
                ? dp[i+1][j+1] + 1
                : Math.max(dp[i+1][j], dp[i][j+1]);
        }
    }
    const result = [];
    let i = 0, j = 0;
    while (i < m || j < n) {
        if (i < m && j < n && oldLines[i] === newLines[j]) {
            result.push({ op: 'ctx', line: oldLines[i] }); i++; j++;
        } else if (j < n && (i >= m || dp[i][j+1] >= dp[i+1][j])) {
            result.push({ op: 'add', line: newLines[j] }); j++;
        } else {
            result.push({ op: 'remove', line: oldLines[i] }); i++;
        }
    }
    return result;
}

function enterProposeMode(proposedText, newBlocks) {
    if (editMode) { discardText(); }
    const current = getNode(tree, path);
    if (!current) { return Promise.resolve({ error: 'no current node', changed: false }); }

    const currentText = (current.items || [])
        .filter(it => it.type === 'text')
        .map(it => it.text)
        .join('\n');

    const diff = diffLines(currentText, proposedText);
    const hasChanges = diff.some(d => d.op !== 'ctx');

    const div = document.getElementById('block-text');
    div.innerHTML = '';
    div.classList.add('propose-mode');

    if (!hasChanges && Object.keys(newBlocks || {}).length === 0) {
        div.classList.remove('propose-mode');
        return Promise.resolve({ result: 'applied', changed: false });
    }

    for (const { op, line } of diff) {
        const row = document.createElement('span');
        row.className = op === 'add' ? 'diff-add' : op === 'remove' ? 'diff-remove' : 'diff-ctx';
        row.textContent = (op === 'add' ? '+ ' : op === 'remove' ? '− ' : '  ') + line;
        div.appendChild(row);
    }

    document.getElementById('propose-bar').classList.add('visible');

    return new Promise((resolve) => {
        _proposePending = { text: proposedText, newBlocks: newBlocks || {}, resolve, hasChanges };
    });
}

function applyPropose() {
    if (!_proposePending) { return; }
    const { text, newBlocks, resolve, hasChanges } = _proposePending;
    _proposePending = null;
    document.getElementById('propose-bar').classList.remove('visible');
    document.getElementById('block-text').classList.remove('propose-mode');
    if (!hasChanges && Object.keys(newBlocks).length === 0) {
        renderContent();
        resolve({ result: 'applied', changed: false });
        return;
    }
    const current = getNode(tree, path);
    vscode.postMessage({ type: 'editText', path: current.path, text, newBlocks });
    resolve({ result: 'applied', changed: true });
}

function discardPropose() {
    if (!_proposePending) { return; }
    const { resolve } = _proposePending;
    _proposePending = null;
    document.getElementById('propose-bar').classList.remove('visible');
    document.getElementById('block-text').classList.remove('propose-mode');
    renderContent();
    resolve({ result: 'discarded', changed: false });
}
// [cf]
// [of]: ctx_menu
// [of]: ctx_show_hide
function showCtxMenu(e, node) {
    e.preventDefault();
    ctxNode = node;
    const menu = document.getElementById('ctx-menu');
    menu.style.left = e.clientX + 'px';
    menu.style.top  = e.clientY + 'px';
    menu.classList.add('visible');
}

function hideCtxMenu() {
    document.getElementById('ctx-menu').classList.remove('visible');
    ctxNode = null;
}
// [cf]

// [of]: ctxRename
function ctxRename() {
    const node = ctxNode;
    hideCtxMenu();
    if (!node) { return; }

    const bar = document.getElementById('save-bar');
    bar.classList.add('visible');
    let inp = document.getElementById('rename-input');
    if (!inp) {
        inp = document.createElement('input');
        inp.id = 'rename-input';
        inp.type = 'text';
        inp.style.cssText = 'flex:1;padding:1px 6px;font-size:inherit;background:var(--vscode-input-background);color:var(--vscode-input-foreground);border:1px solid var(--vscode-focusBorder);outline:none;min-width:80px;max-width:200px';
        bar.insertBefore(inp, bar.firstChild);
    }
    inp.value = node.label;
    inp.style.display = '';
    inp.focus();
    inp.select();

    function done(confirm) {
        const newLabel = inp.value.trim();
        inp.style.display = 'none';
        inp.onkeydown = null;
        if (!editMode) { bar.classList.remove('visible'); }
        if (confirm && newLabel && newLabel !== node.label) {
            vscode.postMessage({ type: 'renameBlock', path: node.path, newLabel });
        }
    }

    inp.onkeydown = (e) => {
        if (e.key === 'Enter')  { e.preventDefault(); done(true); }
        if (e.key === 'Escape') { done(false); }
    };
    setTimeout(() => {
        document.addEventListener('click', function outside(ev) {
            if (ev.target !== inp) { done(false); document.removeEventListener('click', outside); }
        });
    }, 100);
}
// [cf]

function ctxDuplicate() {
    hideCtxMenu();
    vscode.postMessage({ type: 'duplicateBlock', path: ctxNode.path });
}

function ctxRemove() {
    hideCtxMenu();
    vscode.postMessage({ type: 'removeBlock', path: ctxNode.path });
}
// [cf]
// [of]: init
// [of]: buildCtxMenu
function buildCtxMenu() {
    if (document.getElementById('ctx-menu')) { return; }
    const menu = document.createElement('div');
    menu.id = 'ctx-menu';
    menu.innerHTML = `
        <div class="ctx-item" id="ctx-rename">Rename</div>
        <div class="ctx-item" id="ctx-duplicate">Duplicate</div>
        <div class="ctx-separator"></div>
        <div class="ctx-item" id="ctx-remove">Remove</div>
    `;
    document.body.appendChild(menu);
    document.getElementById('ctx-rename').addEventListener('click', ctxRename);
    document.getElementById('ctx-duplicate').addEventListener('click', ctxDuplicate);
    document.getElementById('ctx-remove').addEventListener('click', ctxRemove);

    const cmenu = document.createElement('div');
    cmenu.id = 'chip-menu';
    cmenu.innerHTML = `
        <div class="ctx-item" id="chip-expand">Expand inline</div>
        <div class="ctx-item" id="chip-cut">Cut</div>
    `;
    document.body.appendChild(cmenu);
    document.getElementById('chip-expand').addEventListener('click', () => {
        if (!chipMenuTarget) { return; }
        const { span, item } = chipMenuTarget;
        hideChipMenu();
        flattenChipInline(span, item);
    });
    document.getElementById('chip-cut').addEventListener('click', () => {
        if (!chipMenuTarget) { return; }
        const { span } = chipMenuTarget;
        chipClipboard = [{ label: span.dataset.label, uid: span.dataset.uid }];
        span.remove();
        clearChipSelection();
        hideChipMenu();
    });

    document.addEventListener('click', () => { hideCtxMenu(); hideChipMenu(); });
}
// [cf]

// [of]: message_handler
window.addEventListener('message', (event) => {
    const msg = event.data;
    if (msg.type === 'tree') {
        const fileChanged = msg.file && msg.file !== currentFile;
        tree = msg.tree;
        if (msg.file) { currentFile = msg.file; }
        if (_pendingNavBack) {
            path = _pendingNavBack;
            _pendingNavBack = null;
        } else if (path.length === 0 || fileChanged) {
            path = ['root'];
        }
        pendingSave = false;
        renderColumns();
        // Non sovrascrivere il div in edit mode: l'utente sta editando
        if (!editMode) {
            renderContent();
        }
        if (_pendingFocusAI) {
            const pending = _pendingFocusAI;
            _pendingFocusAI = null;
            applyFocusAI(pending);
        }
    } else if (msg.type === 'focusAI') {
        if (msg.blockPath) { applyFocusAI(msg.blockPath); }
    } else if (msg.type === 'focusUser') {
        markFocus('focus-user', msg.blockPath);
    } else if (msg.type === 'rpc') {
        handleRpc(msg);
    } else if (msg.type === 'error') {
        document.getElementById('block-text').textContent = 'Error: ' + msg.message;
    }
});

function applyFocusAI(blockPath) {
    const parts = blockPath.split('/');
    const node = getNode(tree, parts);
    if (node) {
        _navigatingFromAI = true;
        navigateTo(node);
        _navigatingFromAI = false;
        markFocus('focus-ai', blockPath);
    } else {
        _pendingFocusAI = blockPath;
    }
}
// [cf]
// [of]: rpc_handler
function rpcReply(id, data) {
    vscode.postMessage({ type: 'rpc_response', id, data });
}

function renderTextOf(node) {
    return (node.items || [])
        .filter(it => it.type === 'text')
        .map(it => it.text)
        .join('\n');
}

function handleRpc(msg) {
    const { id, cmd } = msg;
    if (cmd === 'getState') {
        const current = getNode(tree, path);
        const serialized = editMode ? serializeEditDiv() : (current ? renderTextOf(current) : '');
        rpcReply(id, {
            path:     path.join('/'),
            file:     currentFile,
            editMode,
            text:     serialized,
            items:    current ? (current.items || []) : [],
            history:  navHistory.slice(),
        });
    } else if (cmd === 'pushHistory') {
        // Salva posizione corrente in navHistory (usato da /navigateRef lato server)
        navHistory.push({ file: currentFile, path: path.slice() });
        renderNavHistory();
        rpcReply(id, { ok: true, historyLen: navHistory.length });
    } else if (cmd === 'command') {
        if      (msg.action === 'enterEdit')    { enterEditMode();       rpcReply(id, { ok: true }); }
        else if (msg.action === 'saveText')     { saveText();            rpcReply(id, { ok: true }); }
        else if (msg.action === 'discardText')  { discardText();         rpcReply(id, { ok: true }); }
        else if (msg.action === 'navigateBack') { navigateBack();        rpcReply(id, { ok: true }); }
        else if (msg.action === 'historyBack')  { navigateHistoryBack(); rpcReply(id, { ok: true }); }
        else { rpcReply(id, { error: 'unknown action: ' + msg.action }); }
    } else if (cmd === 'propose') {
        if (msg.text === undefined) { rpcReply(id, { error: 'missing text' }); return; }
        enterProposeMode(msg.text, msg.newBlocks || {}).then(result => rpcReply(id, result));
    } else if (cmd === 'select') {
        if (!editMode) { rpcReply(id, { error: 'not in edit mode' }); return; }
        const div = document.getElementById('block-text');
        const rows = Array.from(div.childNodes).filter(n => n.nodeName === 'DIV');
        const from = Math.max(0, msg.from || 0);
        const to   = Math.min(rows.length - 1, msg.to !== undefined ? msg.to : rows.length - 1);
        if (from > to || rows.length === 0) { rpcReply(id, { error: 'invalid range' }); return; }
        const range = document.createRange();
        range.setStart(rows[from], 0);
        range.setEnd(rows[to], rows[to].childNodes.length);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        savedRange = range.cloneRange();
        rpcReply(id, { ok: true, from, to, text: serializeFragment(range.cloneContents()) });
    } else if (cmd === 'wrap') {
        if (!msg.label) { rpcReply(id, { error: 'missing label' }); return; }
        if (!editMode) { rpcReply(id, { error: 'not in edit mode' }); return; }
        const div = document.getElementById('block-text');
        let range = savedRange;
        if (!range) {
            const sel = window.getSelection();
            if (sel && !sel.isCollapsed && sel.rangeCount > 0) { range = sel.getRangeAt(0).cloneRange(); }
        }
        if (!range || range.collapsed) { rpcReply(id, { error: 'no selection' }); return; }
        savedRange = null;
        const fragment = range.cloneContents();
        const selectedText = serializeFragment(fragment).trim();
        range.deleteContents();
        const label = msg.label;
        const current = getNode(tree, path);
        const tempItem = { type: 'block', label, uid: '', path: current.path + '/' + label, start_line: -1, items: [] };
        const chip = makeBlockChip(tempItem);
        range.insertNode(chip);
        const text = serializeEditDiv();
        editMode = false;
        div.contentEditable = 'false';
        div.classList.remove('edit-mode');
        document.getElementById('save-bar').classList.remove('visible');
        vscode.postMessage({ type: 'editText', path: current.path, text, newBlocks: { [label]: selectedText } });
        rpcReply(id, { ok: true, text, selectedText, label });
    } else if (cmd === 'focus') {
        const parts = msg.path ? msg.path.split('/') : [];
        if (parts.length === 0) { rpcReply(id, { error: 'missing path' }); return; }
        const node = getNode(tree, parts);
        if (!node) { rpcReply(id, { error: 'node not found: ' + msg.path }); return; }
        navigateTo(node);
        rpcReply(id, { ok: true, path: path.join('/') });
    } else {
        rpcReply(id, { error: 'unknown rpc cmd: ' + cmd });
    }
}
// [cf]

// [of]: keydown_handler
window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        if (_proposePending) { applyPropose(); } else { saveText(); }
        return;
    }

    // Ctrl+Backspace — torna al caller cross-file (history back)
    if ((e.ctrlKey || e.metaKey) && e.key === 'Backspace') {
        e.preventDefault();
        navigateHistoryBack();
        return;
    }

    if (e.key === 'Escape') {
        if (_proposePending) { discardPropose(); return; }
        if (editMode) { discardText(); return; }
    }

    if (e.altKey && e.key === 'w') {
        e.preventDefault();
        wrapSelection();
        return;
    }

    if (editMode) {
        if (selectedChip) {
            if (e.key === 'Delete' || e.key === 'Backspace') {
                e.preventDefault();
                const chip = selectedChip;
                clearChipSelection();
                chip.remove();
                return;
            }
            if ((e.ctrlKey || e.metaKey) && e.key === 'x') {
                e.preventDefault();
                chipClipboard = [{ label: selectedChip.dataset.label, uid: selectedChip.dataset.uid }];
                selectedChip.remove();
                clearChipSelection();
                return;
            }
            if ((e.ctrlKey || e.metaKey) && e.key === 'c') {
                e.preventDefault();
                chipClipboard = [{ label: selectedChip.dataset.label, uid: selectedChip.dataset.uid }];
                return;
            }
        }
        if ((e.ctrlKey || e.metaKey) && e.key === 'v' && chipClipboard.length > 0) {
            e.preventDefault();
            for (const c of chipClipboard) { insertChipAtCursor(c.label, c.uid); }
            return;
        }

        return;
    }

    if (e.key === 'e') { enterEditMode(); return; }
    if (e.key === 'ArrowLeft' || e.key === 'Backspace') { navigateBack(); return; }
    if (e.key === 'ArrowRight' || e.key === 'Enter') {
        const current = getNode(tree, path);
        if (current) {
            const first = childBlocks(current)[0];
            if (first) { userNavigateTo(first); }
        }
        return;
    }
    if (e.key === 'ArrowUp')   { e.preventDefault(); navigateSibling(-1); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); navigateSibling(+1); return; }
});
// [cf]

// [of]: ensureUI
function ensureUI() {
const contentArea = document.getElementById('content-area');

    if (!document.getElementById('save-bar')) {
        const bar = document.createElement('div');
        bar.id = 'save-bar';
        bar.innerHTML = `
            <span>Unsaved changes</span>
            <button id="btn-save">Save (Ctrl+\u21b5)</button>
            <button class="discard" id="btn-discard">Discard</button>
        `;
        const blockText = document.getElementById('block-text');
        contentArea.insertBefore(bar, blockText);
    }

    if (!document.getElementById('block-text')) {
        const div = document.createElement('div');
        div.id = 'block-text';
        div.setAttribute('spellcheck', 'false');
        contentArea.appendChild(div);
    }

    const oldWrap = document.getElementById('btn-wrap');
    if (oldWrap) { oldWrap.remove(); }
    const btnWrap = document.createElement('button');
    btnWrap.id = 'btn-wrap';
    btnWrap.textContent = 'Wrap';
    btnWrap.style.cssText = 'margin-left:auto;padding:2px 10px;cursor:pointer;font-size:inherit;background:var(--vscode-button-secondaryBackground,#5a5d5e);color:var(--vscode-button-secondaryForeground,#fff);border:none';
    btnWrap.addEventListener('click', () => { wrapSelection(); });
    document.getElementById('save-bar').appendChild(btnWrap);

    document.getElementById('btn-save').onclick    = saveText;
    document.getElementById('btn-discard').onclick = discardText;
    const btnApply   = document.getElementById('btn-apply');
    const btnDiscard = document.getElementById('btn-propose-discard');
    if (btnApply)   { btnApply.onclick   = applyPropose; }
    if (btnDiscard) { btnDiscard.onclick = discardPropose; }

const bt = document.getElementById('block-text');

    bt.addEventListener('mouseup', () => {
        if (!editMode) { return; }
        const sel = window.getSelection();
        if (sel && !sel.isCollapsed && sel.rangeCount > 0) {
            savedRange = sel.getRangeAt(0).cloneRange();
        }
    });

    bt.onclick = (e) => {
        if (editMode && !e.target.classList.contains('block-ref')) {
            clearChipSelection();
        }
    };
    bt.ondblclick = () => {
        if (!editMode) { enterEditMode(); }
    };

    bt.addEventListener('dragover', (e) => {
        if (!editMode) { return; }
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        const range = document.caretRangeFromPoint
            ? document.caretRangeFromPoint(e.clientX, e.clientY)
            : null;
        if (range) {
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        }
    });

    bt.addEventListener('drop', (e) => {
        if (!editMode) { return; }
        e.preventDefault();
        const data = e.dataTransfer.getData('text/plain');
        if (!data.startsWith('__chip__:')) { return; }
        const [, label, uid] = data.split(':');

        const dropRange = document.caretRangeFromPoint
            ? document.caretRangeFromPoint(e.clientX, e.clientY)
            : null;

        const orig = bt.querySelector('.block-ref.dragging');
        if (orig) { orig.remove(); }

        insertChipAtRange(label, uid, dropRange);
    });
}
// [cf]

ensureUI();
buildCtxMenu();
vscode.postMessage({ type: 'ready' });
// [cf]
// [cf]
