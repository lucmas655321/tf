// [of]: root
import * as vscode from 'vscode';
import { MillerPanel } from './millerPanel';

export function activate(context: vscode.ExtensionContext) {
// [of]: register_command
    context.subscriptions.push(
        vscode.commands.registerCommand('textfolding.open', () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) {
                vscode.window.showErrorMessage('TextFolding: no active editor');
                return;
            }
            MillerPanel.createOrShow(context, editor.document);
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('textfolding.openAndClose', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) {
                vscode.window.showErrorMessage('TextFolding: no active editor');
                return;
            }
            const doc = editor.document;
            MillerPanel.createOrShow(context, doc);
            // Wait a bit for Miller to open, then close the original file
            setTimeout(() => {
                // Find and close only the original file editor
                for (const e of vscode.window.visibleTextEditors) {
                    if (e.document.uri.toString() === doc.uri.toString()) {
                        vscode.commands.executeCommand('workbench.action.closeActiveEditor', e.document.uri);
                        break;
                    }
                }
            }, 100);
        })
    );
// [cf]
// [of]: save_watcher
    // Aggiorna il pannello quando il documento viene salvato dall'editor
    context.subscriptions.push(
        vscode.workspace.onDidSaveTextDocument(doc => {
            MillerPanel.refresh(doc);
        })
    );
// [cf]
// [of]: fs_watcher
    // Aggiorna il pannello quando il file cambia su disco (es. tf --write)
    const watcher = vscode.workspace.createFileSystemWatcher('**/*');
    context.subscriptions.push(watcher);
    context.subscriptions.push(
        watcher.onDidChange(uri => {
            MillerPanel.refreshByPath(uri.fsPath);
        })
    );
// [cf]
}

export function deactivate() {
    MillerPanel.dispose();
}
// [cf]
