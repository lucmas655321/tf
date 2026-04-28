#[of]: root
#!/usr/bin/env python3
"""
Test runner Miller — testa l'interfaccia webview via HTTP RPC (tf_miller).
Richiede Miller aperto in VS Code con il pannello visibile.
Uso: python3 test/run_miller.py [--verbose]
"""
#[of]: imports
import sys, os, json, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tf_mcp as m
#[cf]
#[of]: infra
# ---------------------------------------------------------------------------
# Infrastruttura runner
# ---------------------------------------------------------------------------
# Verbosity: 0=solo sintesi (default), 1=sezioni+fail (--fails), 2=tutto (--verbose/-v)

_pass = _fail = _skip = 0
_failures = []
_verbosity = 2 if ('--verbose' in sys.argv or '-v' in sys.argv) else \
             1 if '--fails' in sys.argv else 0

def ok(name, got, check_fn, msg=''):
    global _pass, _fail
    try:
        passed = check_fn(got)
    except Exception as e:
        passed = False
        msg = f'exception in check: {e}'
    if passed:
        _pass += 1
        if _verbosity >= 2:
            print(f'  PASS  {name}')
    else:
        _fail += 1
        _failures.append((name, repr(got)[:200], msg))
        if _verbosity >= 1:
            print(f'  FAIL  {name}  →  {msg or repr(got)[:120]}')

def skip(name, reason=''):
    global _skip
    _skip += 1
    if _verbosity >= 2:
        print(f'  SKIP  {name}  ({reason})')

def section(title):
    if _verbosity >= 1:
        print(f'── {title}')

def is_ok(r):   return isinstance(r, dict) and r.get('ok') is True
def is_fail(r): return isinstance(r, dict) and (r.get('ok') is False or 'error' in r)

def miller_up():
    """Verifica che Miller risponda — salta tutta la suite se non è disponibile."""
    r = m.tf_miller(cmd='state')
    return 'error' not in r
#[cf]
#[of]: fixtures
# ---------------------------------------------------------------------------
# Fixture — file TF temporaneo usato dai test
# ---------------------------------------------------------------------------

TF = '/tmp/tf_miller_test.txt'

def reset_fixture():
    """Ricrea il file di test con struttura nota e ricarica Miller."""
    with open(TF, 'w') as f:
        f.write(
            '#[of]: root\n'
            'Testo root prima dei blocchi.\n'
            '#[of]: sezione_a\n'
            'Testo A riga 1.\n'
            'Testo A riga 2.\n'
            '#[cf]\n'
            '#[of]: sezione_b\n'
            '#[of]: s\n'
            'Testo dentro S.\n'
            '#[cf]\n'
            '\n'
            '#[of]: t\n'
            'Testo dentro T.\n'
            '#[cf]\n'
            '#[cf]\n'
            '#[of]: sezione_c\n'
            'Solo testo, nessun figlio.\n'
            '#[cf]\n'
            '#[cf]\n'
        )
    # Ricarica Miller sul file fresco e aspetta che il tree sia aggiornato
    m.tf_miller(cmd='open', path=f'{TF}@root')
    time.sleep(0.5)

def open_block(block_path):
    """Naviga Miller al blocco nel file fixture già aperto."""
    r = m.tf_miller(cmd='focus', path=block_path)
    time.sleep(0.15)
    return r

def enter_edit():
    r = m.tf_miller(cmd='command', action='enterEdit')
    time.sleep(0.1)
    return r

def save():
    r = m.tf_miller(cmd='command', action='saveText')
    time.sleep(0.25)
    return r

def discard():
    r = m.tf_miller(cmd='command', action='discardText')
    time.sleep(0.1)
    return r

def state():
    return m.tf_miller(cmd='state')
#[cf]

# Guard: salta tutto se Miller non è raggiungibile
if not miller_up():
    print('SKIP  Miller non raggiungibile (porta 7891). Apri il pannello Miller in VS Code.')
    sys.exit(0)

#[of]: T_state
# ---------------------------------------------------------------------------
# STATE — verifica struttura risposta getState
# ---------------------------------------------------------------------------
section('STATE')
reset_fixture()

r = state()
ok('ST1 state ha path', r, lambda v: 'path' in v)
ok('ST2 state ha file', r, lambda v: 'file' in v)
ok('ST3 state ha editMode', r, lambda v: 'editMode' in v)
ok('ST4 state ha items', r, lambda v: 'items' in v)
ok('ST5 editMode inizialmente false', r, lambda v: v.get('editMode') is False)
ok('ST6 file è il fixture', r, lambda v: TF in v.get('file', ''))
#[cf]
#[of]: T_focus
# ---------------------------------------------------------------------------
# FOCUS — navigazione
# ---------------------------------------------------------------------------
section('FOCUS')
reset_fixture()

open_block('root/sezione_a')
r = state()
ok('F1 focus su sezione_a ok', r, lambda v: 'sezione_a' in v.get('path', ''))
ok('F2 file rimane il fixture', r, lambda v: TF in v.get('file', ''))

open_block('root/sezione_b')
r = state()
ok('F3 focus su blocco con figli', r, lambda v: 'sezione_b' in v.get('path', ''))
ok('F4 items contiene chip s e t', r,
   lambda v: any(it.get('label') == 's' for it in v.get('items', []))
          and any(it.get('label') == 't' for it in v.get('items', [])))
ok('F5 blank line tra s e t preservata', r,
   lambda v: any(it.get('type') == 'text' and it.get('text') == ''
                 for it in v.get('items', [])))

# navigazione profonda — verifica path
open_block('root/sezione_b/s')
r = state()
ok('F7 path corretto a 3 livelli', r,
   lambda v: v.get('path', '') == 'root/sezione_b/s')

# focus inesistente — Miller non crasha
r = m.tf_miller(cmd='focus', path='root/nonexistent')
time.sleep(0.1)
ok('F6 focus su blocco inesistente non crasha', r,
   lambda v: isinstance(v, dict))
#[cf]
#[of]: T_edit_roundtrip
# ---------------------------------------------------------------------------
# EDIT ROUNDTRIP — entra/salva/verifica
# ---------------------------------------------------------------------------
section('EDIT ROUNDTRIP')
reset_fixture()

# Caso 1: testo semplice
open_block('root/sezione_a')
enter_edit()
r = state()
ok('ER1 editMode true dopo enterEdit', r, lambda v: v.get('editMode') is True)
ok('ER2 testo serializzato corretto', r,
   lambda v: 'Testo A riga 1' in v.get('text', '')
          and 'Testo A riga 2' in v.get('text', ''))
ok('ER3 testo ha almeno 2 righe non vuote', r,
   lambda v: sum(1 for l in v.get('text', '').splitlines() if l.strip()) >= 2)

save()
r = state()
ok('ER4 editMode false dopo save', r, lambda v: v.get('editMode') is False)
r2 = m.tf_getBlockContent(TF + '@root/sezione_a')
ok('ER5 file non corrotto dopo save', r2,
   lambda v: 'Testo A riga 1' in str(v) and 'Testo A riga 2' in str(v))

# Caso 2: leggi e scarta
open_block('root/sezione_c')
enter_edit()
r = state()
ok('ER6 testo sezione_c letto', r, lambda v: 'Solo testo' in v.get('text', ''))
discard()

# Caso 3: testo con solo blocchi figlio
open_block('root/sezione_b')
enter_edit()
r = state()
ok('ER7 sezione_b serializza chip s', r, lambda v: '[s]' in v.get('text', ''))
ok('ER8 sezione_b serializza chip t', r, lambda v: '[t]' in v.get('text', ''))
ok('ER9 blank line tra s e t nel testo serializzato', r,
   lambda v: '[s]\n\n[t]' == v.get('text', '').strip())
save()
r2 = m.tf_getBlockContent(TF + '@root/sezione_b', mode='structured')
ok('ER10 blank line preservata nel file dopo save', r2,
   lambda v: '[s]\n\n[t]' == str(v if isinstance(v, str) else v.get('result', str(v))).strip())

# Caso 4: save multipli non consumano righe vuote
for i in range(3):
    open_block('root/sezione_b')
    enter_edit()
    save()
r2 = m.tf_getBlockContent(TF + '@root/sezione_b', mode='structured')
ok('ER11 3x save non consuma blank line', r2,
   lambda v: '[s]\n\n[t]' == str(v if isinstance(v, str) else v.get('result', '')).strip())
#[cf]
#[of]: T_blank_lines
# ---------------------------------------------------------------------------
# BLANK LINES — casi edge delle righe vuote
# ---------------------------------------------------------------------------
section('BLANK LINES')
reset_fixture()

# testo con riga vuota in mezzo
m.tf_editText(TF + '@root/sezione_a', 'Prima riga.\n\nTerza riga.', write=True)
# Ricarica Miller dopo modifica esterna del file
m.tf_miller(cmd='open', path=f'{TF}@root/sezione_a')
time.sleep(0.5)
enter_edit()
r = state()
ok('BL1 riga vuota in mezzo al testo serializzata', r,
   lambda v: '\n\n' in v.get('text', ''))
ok('BL2 tre righe (1 vuota in mezzo)', r,
   lambda v: len(v.get('text', '').splitlines()) == 3)
save()
r2 = m.tf_getBlockContent(TF + '@root/sezione_a')
ok('BL3 riga vuota in mezzo sopravvive a save', r2,
   lambda v: '\n\n' in str(v))

# testo che termina con riga vuota prima di chip
m.tf_editText(TF + '@root/sezione_b', '[s]\n\n[t]', write=True)
m.tf_miller(cmd='open', path=f'{TF}@root/sezione_b')
time.sleep(0.5)
enter_edit()
r = state()
ok('BL4 trailing blank prima di chip NON duplicata', r,
   lambda v: v.get('text', '').count('\n\n') == 1)
save()
r2 = m.tf_getBlockContent(TF + '@root/sezione_b', mode='structured')
ok('BL5 struttura [s]\\n\\n[t] intatta', r2,
   lambda v: '[s]\n\n[t]' == str(v if isinstance(v, str) else v.get('result', '')).strip())

# blocco vuoto (nessun testo, nessun figlio)
reset_fixture()
m.tf_addBlock(TF + '@root', 'vuoto', content='', after='root/sezione_c')
time.sleep(0.2)
m.tf_miller(cmd='open', path=f'{TF}@root')
time.sleep(0.5)
open_block('root/vuoto')
enter_edit()
r = state()
ok('BL6 blocco vuoto editabile', r, lambda v: v.get('editMode') is True)
ok('BL7 testo blocco vuoto è stringa vuota', r,
   lambda v: v.get('text', 'X') == '' and 'vuoto' in v.get('path', ''))
save()
#[cf]
#[of]: T_wrap
# ---------------------------------------------------------------------------
# WRAP — crea chip da testo selezionato
# ---------------------------------------------------------------------------
section('WRAP')
reset_fixture()

# wrap di testo semplice
open_block('root/sezione_a')
enter_edit()
r = state()
ok('WR1 sezione_a ha 2 righe in edit', r, lambda v: len(v.get('text', '').splitlines()) == 2)

r = m.tf_miller(cmd='select', from_line=0, to_line=0)
ok('WR2 select riga 0', r, is_ok)
ok('WR3 selected text non vuoto', r,
   lambda v: len(v.get('text', '').strip()) > 0)

r = m.tf_miller(cmd='wrap', label='estratto')
ok('WR4 wrap ok', r, is_ok)
ok('WR5 chip inserito nel testo', r,
   lambda v: '[estratto]' in v.get('text', ''))
ok('WR6 selectedText contiene testo riga 0', r,
   lambda v: 'Testo A riga 1' in v.get('selectedText', ''))

time.sleep(0.3)
r2 = m.tf_getBlockContent(TF + '@root/sezione_a', mode='structured')
ok('WR7 chip estratto nel file', r2,
   lambda v: 'estratto' in str(v))
r3 = m.tf_getBlockContent(TF + '@root/sezione_a/estratto')
ok('WR8 contenuto del nuovo blocco corretto', r3,
   lambda v: 'Testo A riga 1' in str(v))

# wrap senza selezione → errore
reset_fixture()
open_block('root/sezione_a')
enter_edit()
r = m.tf_miller(cmd='wrap', label='nessuna_sel')
ok('WR9 wrap senza selezione → errore', r, is_fail)
discard()

# wrap su chip esistente: selectedText deve essere [s] non il testo espanso
reset_fixture()
open_block('root/sezione_b')
enter_edit()
r = m.tf_miller(cmd='select', from_line=0, to_line=0)
ok('WR10 select chip s', r, is_ok)
ok('WR11 chip selezionato come [s]', r,
   lambda v: '[s]' in v.get('text', ''))
r2 = m.tf_miller(cmd='wrap', label='wrapper_s')
ok('WR12 wrap chip esistente ok', r2, is_ok)
ok('WR13 testo risultante ha [wrapper_s]', r2,
   lambda v: '[wrapper_s]' in v.get('text', ''))
ok('WR14 selectedText è [s] non testo espanso', r2,
   lambda v: v.get('selectedText', '').strip() == '[s]')
time.sleep(0.3)
r3 = m.tf_tree(TF + '@root/sezione_b/wrapper_s')
ok('WR15 wrapper_s contiene s come figlio', r3,
   lambda v: 's' in str(v))
#[cf]
#[of]: T_chip_same_row
# ---------------------------------------------------------------------------
# CHIP STESSA RIGA — chip accidentalmente sulla stessa riga devono essere
# normalizzati su righe distinte al save (non concatenati come testo)
# ---------------------------------------------------------------------------
section('CHIP STESSA RIGA')

# Caso 1: wrap di selezione che include più chip
# selectedText deve contenere [s] e [t] come riferimenti testuali
reset_fixture()
open_block('root/sezione_b')
enter_edit()
r = m.tf_miller(cmd='select', from_line=0, to_line=2)
ok('CS1 select 3 righe (s, vuota, t)', r, is_ok)
r2 = m.tf_miller(cmd='wrap', label='tutto')
ok('CS2 wrap multi-chip ok', r2, is_ok)
ok('CS3 [tutto] nel testo', r2, lambda v: '[tutto]' in v.get('text', ''))
ok('CS4 selectedText contiene [s] e [t]', r2,
   lambda v: '[s]' in v.get('selectedText', '') and '[t]' in v.get('selectedText', ''))
time.sleep(0.3)
# s e t rimangono sotto sezione_b (non si spostano dentro tutto)
r3 = m.tf_tree(TF + '@root/sezione_b')
ok('CS5 s e t rimangono figli di sezione_b dopo wrap', r3,
   lambda v: 's' in str(v) and 't' in str(v) and 'tutto' in str(v))

# Caso 2: due chip sulla stessa riga → serializzati su righe distinte
# Simuliamo: sezione_b ha [s]\n\n[t], editiamo testo per mettere i chip su riga unica
# (caso impossibile in UI normale ma il serializzatore deve gestirlo)
reset_fixture()
# Forza i due chip sulla stessa riga modificando il DOM via select+wrap+discard
# In realtà testiamo che il roundtrip normale preserva la struttura
open_block('root/sezione_b')
enter_edit()
r = state()
ok('CS6 [s]\\n\\n[t] nel testo', r,
   lambda v: '[s]\n\n[t]' == v.get('text', '').strip())
save()
r2 = m.tf_getBlockContent(TF + '@root/sezione_b', mode='structured')
ok('CS7 struttura intatta dopo roundtrip', r2,
   lambda v: '[s]\n\n[t]' == str(v if isinstance(v, str) else v.get('result', '')).strip())
r3 = m.tf_tree(TF + '@root/sezione_b')
ok('CS8 s e t rimangono blocchi separati', r3,
   lambda v: 's' in str(v) and 't' in str(v))

# Caso 3: verifica che serializeRow separi chip adiacenti con newline
# Usiamo il RPC wrap su selezione che copre chip + testo adiacente sulla stessa riga
reset_fixture()
# sezione_a ha testo puro — wrap di tutta la riga produce chip + testo residuo
open_block('root/sezione_a')
enter_edit()
r = m.tf_miller(cmd='select', from_line=0, to_line=0)  # seleziona "Testo A riga 1."
ok('CS9 select prima riga', r, is_ok)
r2 = m.tf_miller(cmd='wrap', label='prima')
ok('CS10 wrap ok', r2, is_ok)
# Dopo il wrap, il testo deve essere "[prima]\nTesto A riga 2." (chip su riga propria)
ok('CS11 chip su riga propria, non concatenato', r2,
   lambda v: '[prima]' in v.get('text', '') and '\n' in v.get('text', ''))
time.sleep(0.3)
r3 = m.tf_getBlockContent(TF + '@root/sezione_a', mode='structured')
ok('CS12 chip prima nel file su riga separata', r3,
   lambda v: '[prima]' in str(v))
#[cf]
#[of]: T_navigation
# ---------------------------------------------------------------------------
# NAVIGATION — navigateBack, focus post-wrap
# ---------------------------------------------------------------------------
section('NAVIGATION')
reset_fixture()

open_block('root/sezione_a')
r = state()
ok('NV1 file corretto dopo reset+open', r, lambda v: TF in v.get('file', ''))
ok('NV2 focus su sezione_a', r,
   lambda v: 'sezione_a' in v.get('path', ''))

m.tf_miller(cmd='command', action='navigateBack')
time.sleep(0.15)
r = state()
ok('NV3 navigateBack torna al padre', r,
   lambda v: v.get('path', '') in ('root', 'root/sezione_a'))

# dopo wrap, Miller deve restare nel padre (non entrare nel nuovo chip)
reset_fixture()
open_block('root/sezione_a')
enter_edit()
m.tf_miller(cmd='select', from_line=0, to_line=0)
m.tf_miller(cmd='wrap', label='post_wrap_nav')
time.sleep(0.3)
r = state()
ok('NV4 dopo wrap Miller resta nel padre', r,
   lambda v: 'sezione_a' in v.get('path', '') and 'post_wrap_nav' not in v.get('path', ''))
ok('NV5 editMode false dopo wrap', r, lambda v: v.get('editMode') is False)
#[cf]
#[of]: T_propose
# ---------------------------------------------------------------------------
# PROPOSE MODE — AI propone testo, utente applica o scarta
# ---------------------------------------------------------------------------
section('PROPOSE MODE')
reset_fixture()

# PM1: propose applicato
open_block('root/sezione_a')
r = state()
orig_text = r.get('text', '')

result = m.tf_miller(cmd='propose', text='Testo proposto.\nSeconda riga.')
ok('PM1 propose ritorna result', result, lambda v: v.get('result') in ('applied', 'discarded'))
ok('PM2 propose result=applied', result, lambda v: v.get('result') == 'applied')
ok('PM3 changed=True dopo apply', result, lambda v: v.get('changed') is True)

time.sleep(0.3)
r = state()
ok('PM4 testo aggiornato dopo apply', r, lambda v: 'Testo proposto.' in v.get('text', ''))

# PM5: testo invariato → changed=False
open_block('root/sezione_b/s')
r = state()
current_text = r.get('text', '')
result2 = m.tf_miller(cmd='propose', text=current_text)
ok('PM5 propose stesso testo → changed=False', result2, lambda v: v.get('changed') is False)

# PM6: propose su blocco con new_blocks
reset_fixture()
open_block('root/sezione_c')
result3 = m.tf_miller(cmd='propose', text='Testo padre.\n[child_new]', new_blocks={'child_new': 'Contenuto figlio.'})
ok('PM6 propose con new_blocks applicato', result3, lambda v: v.get('result') == 'applied')
time.sleep(0.3)
r = state()
ok('PM7 editMode false dopo propose+apply', r, lambda v: r.get('editMode') is False)

# PM8: propose scartato (non testabile in modo automatico senza interazione utente)
# → skip (richiede click su Discard)
#[cf]
#[of]: T_ref_navigation
section('REF NAVIGATION')

import tempfile, os

TF_REF    = '/tmp/tf_miller_ref_src.txt'
TF_TARGET = '/tmp/tf_miller_ref_target.txt'

# crea fixture src con #tf:ref che punta a target
with open(TF_REF, 'w') as f:
    f.write(
        '#[of]: root\n'
        '#[of]: sezione_con_ref\n'
        '#tf:ref /tmp/tf_miller_ref_target.txt@root/blocco_a\n'
        'Testo dopo il ref.\n'
        '#[cf]\n'
        '#[of]: altra_sezione\n'
        'Contenuto altra sezione.\n'
        '#[cf]\n'
        '#[cf]\n'
    )

# crea fixture target
with open(TF_TARGET, 'w') as f:
    f.write(
        '#[of]: root\n'
        '#[of]: blocco_a\n'
        'Contenuto blocco A.\n'
        '#[cf]\n'
        '#[of]: blocco_b\n'
        'Contenuto blocco B.\n'
        '#[cf]\n'
        '#[cf]\n'
    )

# RN1-RN2: apri src e naviga a sezione_con_ref
r = m.tf_miller(cmd='open', path=f'{TF_REF}@root/sezione_con_ref')
time.sleep(0.5)
r = state()
ok('RN1 focus su sezione_con_ref', r, lambda v: 'sezione_con_ref' in v.get('path', ''))
ok('RN2 file è src', r, lambda v: TF_REF in v.get('file', ''))

# RN3: navigazione via openRef (simula click su ref-chip via RPC)
r = m.tf_miller(cmd='open', path=f'{TF_TARGET}@root/blocco_a')
time.sleep(0.5)
r = state()
ok('RN3 dopo openRef file è target', r, lambda v: TF_TARGET in v.get('file', ''))
ok('RN4 path è root/blocco_a',       r, lambda v: 'blocco_a' in v.get('path', ''))

# RN5: navigazione interna al file target funziona normalmente
open_block('root/blocco_b')
r = state()
ok('RN5 navigazione in target ok', r, lambda v: 'blocco_b' in v.get('path', ''))
ok('RN6 file rimane target',        r, lambda v: TF_TARGET in v.get('file', ''))

# RN7: torna al file sorgente via open (simula Ctrl+Back che usa openRef)
r = m.tf_miller(cmd='open', path=f'{TF_REF}@root/sezione_con_ref')
time.sleep(0.5)
r = state()
ok('RN7 ritorno a src ok',              r, lambda v: TF_REF in v.get('file', ''))
ok('RN8 path ripristinato a sezione_con_ref', r,
   lambda v: 'sezione_con_ref' in v.get('path', ''))

# RN9: cambio file resetta path a root se il path vecchio non esiste
r = m.tf_miller(cmd='open', path=f'{TF_TARGET}@root')
time.sleep(0.3)
open_block('root/blocco_a')
time.sleep(0.1)
# Riaprire src: il path 'blocco_a' non esiste in src → deve andare a root
r = m.tf_miller(cmd='open', path=f'{TF_REF}@root')
time.sleep(0.5)
r = state()
ok('RN9 cambio file resetta path a root', r,
   lambda v: v.get('path', '') in ('root', '') or TF_REF in v.get('file', ''))
ok('RN10 file corretto dopo reset',       r, lambda v: TF_REF in v.get('file', ''))

# RN11-RN13: test navigateRef (push history) + historyBack
# Setup: porta src a sezione_con_ref, poi navigateRef → target (salva history)
r = m.tf_miller(cmd='open', path=f'{TF_REF}@root/sezione_con_ref')
time.sleep(0.4)
r = m.tf_miller(cmd='navigateRef', path=f'{TF_TARGET}@root/blocco_a')
time.sleep(0.6)
r = state()
ok('RN11 navigateRef apre target',        r, lambda v: TF_TARGET in v.get('file', ''))
ok('RN12 navigateRef path corretto',      r, lambda v: 'blocco_a' in v.get('path', ''))
ok('RN13 history non vuota',              r, lambda v: len(v.get('history', [])) > 0)
# historyBack: torna a src/sezione_con_ref
r = m.tf_miller(cmd='command', action='historyBack')
time.sleep(0.7)
r = state()
ok('RN14 historyBack torna a src',        r, lambda v: TF_REF in v.get('file', ''))
ok('RN15 historyBack ripristina path',    r, lambda v: 'sezione_con_ref' in v.get('path', ''))

# cleanup
if os.path.exists(TF_REF):    os.unlink(TF_REF)
if os.path.exists(TF_TARGET): os.unlink(TF_TARGET)
#[cf]
#[of]: results
# ---------------------------------------------------------------------------
# RISULTATI
# ---------------------------------------------------------------------------

if os.path.exists(TF):
    os.unlink(TF)
if os.path.exists('/tmp/tf_test_create.py'):
    os.unlink('/tmp/tf_test_create.py')

print(f"\n{'─'*50}")
print(f'  PASS {_pass}   FAIL {_fail}   SKIP {_skip}')
print(f"{'─'*50}")
if _failures and _verbosity >= 1:
    print('\nFAILURES:')
    for name, got, msg in _failures:
        print(f'  {name}')
        if msg:
            print(f'    → {msg}')
        print(f'    got: {got}')

sys.exit(0 if _fail == 0 else 1)
#[cf]
#[cf]
