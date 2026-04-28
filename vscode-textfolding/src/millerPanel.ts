// [of]: root
// [of]: imports
import * as vscode from 'vscode';
import * as path from 'path';
import * as http from 'http';
import { Backend } from './backend';
// [cf]
// [of]: MillerPanel
export class MillerPanel {
    private static instance: MillerPanel | undefined;

    private readonly panel:   vscode.WebviewPanel;
    private readonly backend: Backend;
    private docPath: string;
    private pendingFocusAI: string | null = null;

// [of]: constructor
    private constructor(
        private readonly context: vscode.ExtensionContext,
        doc: vscode.TextDocument,
    ) {
        this.docPath = doc.uri.fsPath;
        this.panel = vscode.window.createWebviewPanel(
            'miller', 'Miller',
            vscode.ViewColumn.Beside,
            { enableScripts: true, retainContextWhenHidden: true }
        );
        const cfg = vscode.workspace.getConfiguration('textfolding');
        this.backend = new Backend(
            cfg.get<string>('pythonPath', 'python3'),
            Backend.resolveParserPath(context),
        );
        this.panel.webview.html = this.buildHtml(context);
        this.panel.webview.onDidReceiveMessage(msg => this.handleMessage(msg));

        // Quando il pannello torna visibile, rimanda il tree (potrebbe essere stato perso)
        this.panel.onDidChangeViewState(e => {
            if (e.webviewPanel.visible) { this.sendTree(); }
        });

        // HTTP RPC server — permette pilotaggio programmatico di Miller (AI autonoma, test).
        // Porta 7891. Endpoints: POST /command, POST /focus, POST /open, POST /select, POST /wrap, POST /propose, POST /navigateRef, GET /state
        const rpcPending = new Map<string, (data: unknown) => void>();
        this.panel.webview.onDidReceiveMessage(msg => {
            if (msg.type === 'rpc_response') {
                const resolve = rpcPending.get(msg.id);
                if (resolve) { rpcPending.delete(msg.id); resolve(msg.data); }
            }
        });

        const sendRpc = (cmd: string, params: Record<string, unknown> = {}): Promise<unknown> => {
            return new Promise((resolve) => {
                const id = Math.random().toString(36).slice(2);
                rpcPending.set(id, resolve);
                this.panel.webview.postMessage({ type: 'rpc', id, cmd, ...params });
                setTimeout(() => { rpcPending.delete(id); resolve({ error: 'timeout' }); }, 30000); // 30s per propose (attende utente)
            });
        };

        const rpcServer = http.createServer(async (req, res) => {
            const send = (status: number, data: unknown) => {
                res.setHeader('Content-Type', 'application/json');
                res.writeHead(status);
                res.end(JSON.stringify(data));
            };

            let body = '';
            req.on('data', c => body += c);
            await new Promise(r => req.on('end', r));

            const url = req.url ?? '/';

            if (req.method === 'GET' && url === '/state') {
                send(200, await sendRpc('getState'));
                return;
            }

            let payload: Record<string, unknown> = {};
            try { if (body) { payload = JSON.parse(body); } } catch { send(400, { error: 'invalid JSON' }); return; }

            if (req.method === 'POST' && url === '/focus') {
                if (!payload.path) { send(400, { error: 'missing path' }); return; }
                this.panel.webview.postMessage({ type: 'focusAI', blockPath: payload.path, force: true });
                send(200, { ok: true });
            } else if (req.method === 'POST' && url === '/open') {
                if (!payload.file) { send(400, { error: 'missing file' }); return; }
                const blockPath = (payload.path as string) || 'root';
                await MillerPanel.openFromAI(context, payload.file as string, blockPath);
                send(200, { ok: true, file: payload.file, path: blockPath });
            } else if (req.method === 'POST' && url === '/command') {
                send(200, await sendRpc('command', { action: payload.action }));
            } else if (req.method === 'POST' && url === '/navigateRef') {
                // Simula click ref-chip: push history nel frontend, poi apre il file target
                const target = payload.target as string;
                if (!target) { send(400, { error: 'missing target' }); return; }
                // 1) push history nel webview (senza aprire il file — il webview gestisce solo la history)
                await sendRpc('pushHistory');
                // 2) apri il file target come openFromAI
                const atIdx = target.lastIndexOf('@');
                const filePart  = atIdx >= 0 ? target.slice(0, atIdx) : target;
                const blockPart = atIdx >= 0 ? target.slice(atIdx + 1) : 'root';
                const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? path.dirname(this.docPath);
                const absFile = path.isAbsolute(filePart) ? filePart : path.join(wsRoot, filePart);
                await MillerPanel.openFromAI(context, absFile, blockPart);
                send(200, { ok: true });
            } else if (req.method === 'POST' && url === '/propose') {
                // Mostra diff proposto e blocca finché l'utente non sceglie Apply/Discard.
                // payload: { text: string, newBlocks?: {} }
                if (payload.text === undefined) { send(400, { error: 'missing text' }); return; }
                send(200, await sendRpc('propose', { text: payload.text, newBlocks: payload.newBlocks || {} }));
            } else if (req.method === 'POST' && url === '/select') {
                send(200, await sendRpc('select', { from: payload.from, to: payload.to }));
            } else if (req.method === 'POST' && url === '/wrap') {
                send(200, await sendRpc('wrap', { label: payload.label }));
            } else {
                send(400, { error: 'unknown endpoint' });
            }
        });
        rpcServer.listen(7891, '127.0.0.1', () => {
            console.log('[Miller] RPC server listening on http://127.0.0.1:7891');
        });
        this.panel.onDidDispose(() => {
            rpcServer.close();
            this.backend.dispose();
            MillerPanel.instance = undefined;
        });

        this.writeMillerState(null);
        this.sendTree();
    }
// [cf]
// [of]: sendTree
    // -----------------------------------------------------------------------

    private stateFilePath(): string {
        const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        const base = wsRoot ?? path.dirname(this.docPath);
        return path.join(base, '.tf', 'sessions', 'miller', 'state.json');
    }

    private async sendTree() {
        const resp = await this.backend.send({
            cmd: 'tree',
            file: this.docPath,
            includeText: true,
        });
        if (resp.ok) {
            this.panel.webview.postMessage({ type: 'tree', tree: resp.tree, file: this.docPath });
        } else {
            this.panel.webview.postMessage({ type: 'error', message: resp.error });
        }
        if (this.pendingFocusAI) {
            const blockPath = this.pendingFocusAI;
            this.pendingFocusAI = null;
            setTimeout(() => {
                this.panel.webview.postMessage({ type: 'focusAI', blockPath, force: true });
            }, 100);
        }
    }

    private writeMillerState(focusBlock: string | null) {
        const stateFile = this.stateFilePath();
        const sessDir = path.dirname(stateFile);
        try {
            const fs = require('fs');
            fs.mkdirSync(sessDir, { recursive: true });
            const prev = fs.existsSync(stateFile)
                ? JSON.parse(fs.readFileSync(stateFile, 'utf8')) : {};
            const focuses: Array<Record<string, string>> = prev.focuses ?? [];
            if (focusBlock !== null) {
                const absPath = `${this.docPath}@${focusBlock}`;
                const idx = focuses.findIndex(f => f.user === 'user');
                if (idx >= 0) { focuses[idx] = { user: 'user', path: absPath }; }
                else          { focuses.push({ user: 'user', path: absPath }); }
            }
            const state = {
                ...prev,
                agent_id:    'miller',
                focuses,
                last_active: Math.floor(Date.now() / 1000),
            };
            // rimuovi campi legacy
            delete state.focus_user;
            delete state.focus_ai;
            delete state.kind;
            delete state.file;
            if (!state.started) { state.started = state.last_active; }
            fs.writeFileSync(stateFile, JSON.stringify(state, null, 2));
        } catch { /* ignore */ }
    }
// [cf]
// [of]: handleMessage
    private async handleMessage(msg: Record<string, unknown>) {
        const type = msg.type as string;
// [of]: ui_ops
        if (type === 'ready') {
            await this.sendTree();
            if (this.pendingFocusAI) {
                const blockPath = this.pendingFocusAI;
                this.pendingFocusAI = null;
                this.panel.webview.postMessage({ type: 'focusAI', blockPath, force: true });
            }
            return;
        }

        if (type === 'revealLine') {
            const line = msg.line as number;
            const editor = vscode.window.visibleTextEditors.find(
                e => e.document.uri.fsPath === this.docPath
            );
            if (editor) {
                const pos = new vscode.Position(Math.max(0, line - 1), 0);
                editor.selection = new vscode.Selection(pos, pos);
                setTimeout(() => {
                    editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.AtTop);
                }, 50);
            }
            return;
        }

        if (type === 'setFocusUser') {
            await this.backend.send({
                cmd:       'setFocus',
                file:      this.docPath,
                kind:      'user',
                blockPath: msg.path,
                write:     true,
            });
            this.panel.webview.postMessage({ type: 'focusUser', blockPath: msg.path });
            this.writeMillerState(msg.path as string);
            return;
        }

        if (type === 'openRef') {
            // target: "path/to/file.py@root/blocco" — relativo a wsRoot
            const target = msg.target as string;
            const atIdx = target.lastIndexOf('@');
            const filePart  = atIdx >= 0 ? target.slice(0, atIdx) : target;
            const blockPart = atIdx >= 0 ? target.slice(atIdx + 1) : 'root';
            const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? path.dirname(this.docPath);
            const absFile = path.isAbsolute(filePart) ? filePart : path.join(wsRoot, filePart);
            await MillerPanel.openFromAI(this.context, absFile, blockPart);
            return;
        }
// [cf]
    // [of]: edit_ops
        if (type === 'editText') {
            const payload: Record<string, unknown> = {
                cmd:   'editText',
                file:  this.docPath,
                path:  msg.path,
                text:  msg.text,
                write: true,
            };
            if (msg.newBlocks) { payload.newBlocks = msg.newBlocks; }
            const resp = await this.backend.send(payload);
            if (!resp.ok) {
                vscode.window.showErrorMessage(`TextFolding editText path="${msg.path}": ${resp.error}`);
            }
            await this.sendTree();
            return;
        }

        if (type === 'renameBlock') {
            const resp = await this.backend.send({
                cmd:      'renameBlock',
                file:     this.docPath,
                path:     msg.path,
                newLabel: msg.newLabel,
                write:    true,
            });
            if (!resp.ok) {
                vscode.window.showErrorMessage(`TextFolding: ${resp.error}`);
            }
            await this.sendTree();
            return;
        }

        if (type === 'removeBlock') {
            const confirm = await vscode.window.showWarningMessage(
                `Remove block "${msg.path}"?`, 'Yes', 'No'
            );
            if (confirm !== 'Yes') { return; }
            const resp = await this.backend.send({
                cmd:   'removeBlock',
                file:  this.docPath,
                path:  msg.path,
                write: true,
            });
            if (!resp.ok) {
                vscode.window.showErrorMessage(`TextFolding: ${resp.error}`);
            }
            await this.sendTree();
            return;
        }

        if (type === 'duplicateBlock') {
            const resp = await this.backend.send({
                cmd:   'duplicateBlock',
                file:  this.docPath,
                path:  msg.path,
                write: true,
            });
            if (!resp.ok) {
                vscode.window.showErrorMessage(`TextFolding: ${resp.error}`);
            }
            await this.sendTree();
            return;
        }

        if (type === 'wrapText') {
            const resp = await this.backend.send({
                cmd:        'wrapText',
                file:       this.docPath,
                parentPath: msg.parentPath,
                label:      msg.label,
                text:       msg.text,
                write:      true,
            });
            if (!resp.ok) {
                vscode.window.showErrorMessage(`TextFolding wrapText: ${resp.error}`);
            }
            await this.sendTree();
        }
    // [cf]
    }
// [cf]
// [of]: buildHtml
    // -----------------------------------------------------------------------

    private buildHtml(context: vscode.ExtensionContext): string {
        const mediaPath = path.join(context.extensionPath, 'src', 'media');
        const toUri = (f: string) =>
            this.panel.webview.asWebviewUri(vscode.Uri.file(path.join(mediaPath, f)));

        const bust = Date.now();
        return `<!DOCTYPE html>
<!-- ${bust} -->
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy"
  content="default-src 'none';
           style-src ${this.panel.webview.cspSource} 'unsafe-inline';
           script-src ${this.panel.webview.cspSource} 'unsafe-inline';">
<link rel="stylesheet" href="${toUri('miller.css')}">
<link rel="stylesheet" href="${toUri('prism.css')}">
</head>
<body>
<div id="columns"></div>
<div id="nav-history-bar"></div>
<div id="content-area">
  <div id="block-header"></div>
  <div id="save-bar">
    <span>Unsaved changes</span>
    <button id="btn-save">Save (Ctrl+↵)</button>
    <button class="discard" id="btn-discard">Discard</button>
  </div>
  <div id="propose-bar">
    <span class="propose-label">AI proposes:</span>
    <button id="btn-apply">✓ Apply</button>
    <button class="discard" id="btn-propose-discard">✗ Discard</button>
  </div>
  <div id="block-text" spellcheck="false"></div>
</div>
<script src="${toUri('prism.js')}"></script>
<script src="${toUri('prism-python.js')}"></script>
<script src="${toUri('prism-typescript.js')}"></script>
<script src="${toUri('prism-css.js')}"></script>
<script src="${toUri('prism-markdown.js')}"></script>
<script src="${toUri('miller.js')}"></script>
</body>
</html>`;
    }
// [cf]
// [of]: static_api
    // -----------------------------------------------------------------------
    // Static API

    static createOrShow(context: vscode.ExtensionContext, doc: vscode.TextDocument, reveal = true) {
        if (MillerPanel.instance) {
            MillerPanel.instance.docPath = doc.uri.fsPath;
            if (reveal) { MillerPanel.instance.panel.reveal(vscode.ViewColumn.Beside); }
            MillerPanel.instance.sendTree();
            return;
        }
        MillerPanel.instance = new MillerPanel(context, doc);
    }

    static refresh(doc: vscode.TextDocument) {
        if (MillerPanel.instance?.docPath === doc.uri.fsPath) {
            MillerPanel.instance.sendTree();
        }
    }

    static refreshByPath(fsPath: string) {
        if (MillerPanel.instance?.docPath === fsPath) {
            MillerPanel.instance.sendTree();
        }
    }

    static dispose() {
        MillerPanel.instance?.panel.dispose();
    }

    /**
     * Aperto dall'AI via focus_ai in sessions/miller/state.json.
     * - Miller non esiste: crea pannello, pendingFocusAI viene consumato da ready handler
     * - File diverso: imposta pending, poi createOrShow chiama sendTree che lo consuma
     * - Stesso file: ricarica il tree (il file potrebbe essere cambiato) poi manda focusAI
     */
    static async openFromAI(
        context: vscode.ExtensionContext,
        filePath: string,
        focusAI: string,
    ) {
        if (!MillerPanel.instance) {
            // Caso 1: Miller non esiste — ready handler consumerà pendingFocusAI
            let doc: vscode.TextDocument;
            try { doc = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath)); }
            catch { return; }
            MillerPanel.instance = new MillerPanel(context, doc);
            MillerPanel.instance.pendingFocusAI = focusAI;
        } else if (MillerPanel.instance.docPath !== filePath) {
            // Caso 2: file diverso — sendTree consumerà pendingFocusAI
            let doc: vscode.TextDocument;
            try { doc = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath)); }
            catch { return; }
            MillerPanel.instance.pendingFocusAI = focusAI;
            MillerPanel.createOrShow(context, doc, false);
        } else {
            // Caso 3: stesso file — ricarica tree (file potrebbe essere cambiato) poi focus
            MillerPanel.instance.pendingFocusAI = focusAI;
            MillerPanel.instance.sendTree();
        }
    }
// [cf]
}
// [cf]
// [cf]
