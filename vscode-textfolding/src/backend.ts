// [of]: root
// [of]: imports
import * as cp from 'child_process';
import * as readline from 'readline';
import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
// [cf]

// [of]: types
interface BackendResponse {
    ok: boolean;
    error?: string;
    [key: string]: unknown;
}

type PendingRequest = {
    resolve: (v: BackendResponse) => void;
    reject:  (e: Error) => void;
};
// [cf]

// [of]: Backend
export class Backend {
    private proc:    cp.ChildProcess | null = null;
    private rl:      readline.Interface | null = null;
    private queue:   PendingRequest[] = [];
    private ready:   boolean = false;

    constructor(
        private readonly pythonPath: string,
        private readonly parserPath: string,
    ) {}

// [of]: ensureStarted
    private ensureStarted(): Promise<void> {
        if (this.ready) { return Promise.resolve(); }

        return new Promise((resolve, reject) => {
            const args = [this.parserPath, 'dummy', '--server'];
            this.proc = cp.spawn(this.pythonPath, args, {
                stdio: ['pipe', 'pipe', 'pipe'],
            });

            this.proc.on('error', (err) => {
                reject(new Error(`Failed to start backend: ${err.message}`));
            });

            this.proc.stderr?.on('data', (data: Buffer) => {
                console.error('[TextFolding backend]', data.toString());
            });

            this.rl = readline.createInterface({ input: this.proc.stdout! });
            this.rl.on('line', (line) => {
                const pending = this.queue.shift();
                if (!pending) { return; }
                try {
                    pending.resolve(JSON.parse(line) as BackendResponse);
                } catch {
                    pending.reject(new Error(`Invalid JSON from backend: ${line}`));
                }
            });

            this.ready = true;
            resolve();
        });
    }
// [cf]

// [of]: send
    async send(req: Record<string, unknown>): Promise<BackendResponse> {
        await this.ensureStarted();
        return new Promise((resolve, reject) => {
            this.queue.push({ resolve, reject });
            const line = JSON.stringify(req) + '\n';
            this.proc!.stdin!.write(line);
        });
    }
// [cf]

// [of]: init
    async init(filePath: string): Promise<BackendResponse> {
        return this.send({ cmd: 'init', path: filePath });
    }
// [cf]

// [of]: dispose
    dispose() {
        this.rl?.close();
        this.proc?.kill();
        this.proc  = null;
        this.ready = false;
    }
// [cf]

// [of]: resolveParserPath
    static resolveParserPath(context: vscode.ExtensionContext): string {
        const cfg = vscode.workspace.getConfiguration('textfolding');
        const configured = cfg.get<string>('parserPath', '');
        if (configured) { return configured; }
        // default: cerca tf_backend.py nella stessa dir dell'extension
        const candidates = [
            path.join(context.extensionPath, 'tf_backend.py'),
            path.join(context.extensionPath, '..', 'tf_backend.py'),
        ];
        for (const p of candidates) {
            if (fs.existsSync(p)) { return p; }
        }
        return 'tf_backend.py'; // fallback: PATH
    }
}
// [cf]
// [cf]
// [cf]
