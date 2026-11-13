#!/usr/bin/env python3
"""Sistema de Almoxarifado - Caio Pereira. Python 3, somente biblioteca padrão."""
import json, os, sqlite3, hashlib, hmac, secrets, threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, 'almoxarifado.db')
SESSIONS = {}
LOCK = threading.Lock()


def connect():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    return db


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 180000)
    return salt.hex() + ':' + digest.hex()


def check_password(password, stored):
    try:
        salt_hex, digest_hex = stored.split(':', 1)
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt_hex), 180000).hex()
        return hmac.compare_digest(actual, digest_hex)
    except (ValueError, TypeError):
        return False


def init_db():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('operador','administrador')),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('entrada','saida')),
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            user_id INTEGER NOT NULL, username TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(id)
        );
        CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
        CREATE INDEX IF NOT EXISTS idx_movements_date ON movements(created_at);
        ''')
        if not db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            now = datetime.now().astimezone().isoformat(timespec='seconds')
            db.execute('INSERT INTO users(username,password,role,created_at) VALUES(?,?,?,?)',
                       ('admin', hash_password('admin123'), 'administrador', now))
            db.execute('INSERT INTO users(username,password,role,created_at) VALUES(?,?,?,?)',
                       ('operador', hash_password('operador123'), 'operador', now))


def record_movement(db, product_id, kind, quantity, user):
    if kind not in ('entrada', 'saida'):
        raise ValueError('Tipo de movimentação inválido.')
    if not isinstance(quantity, int) or quantity <= 0:
        raise ValueError('A quantidade deve ser um número inteiro maior que zero.')
    product = db.execute('SELECT * FROM products WHERE id=?', (product_id,)).fetchone()
    if not product:
        raise ValueError('Produto não encontrado.')
    current = product['quantity']
    if kind == 'saida' and quantity > current:
        raise ValueError(f'Saída não permitida: estoque insuficiente. Disponível: {current}. Solicitado: {quantity}.')
    new_quantity = current + quantity if kind == 'entrada' else current - quantity
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    db.execute('UPDATE products SET quantity=?, updated_at=? WHERE id=?', (new_quantity, now, product_id))
    db.execute('INSERT INTO movements(product_id,kind,quantity,user_id,username,created_at) VALUES(?,?,?,?,?,?)',
               (product_id, kind, quantity, user['id'], user['username'], now))
    return new_quantity


HTML = r'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Almoxarifado | Caio Pereira</title>
<style>
*{box-sizing:border-box}body{margin:0;font:15px Arial,sans-serif;background:#f3f5f8;color:#202938}header{background:#183653;color:white;padding:18px 5%;display:flex;justify-content:space-between;align-items:center;gap:12px}header h1{font-size:20px;margin:0}.wrap{max-width:1050px;margin:28px auto;padding:0 16px}.panel{background:white;padding:22px;border-radius:9px;box-shadow:0 2px 10px #172b3a12;margin-bottom:18px}h2{font-size:19px;margin:0 0 16px}input,select,button{font:inherit;padding:10px;border:1px solid #ccd3dc;border-radius:5px}input,select{max-width:100%}button{background:#1e5b87;color:white;border:0;cursor:pointer}button.secondary{background:#526273}button.danger{background:#a83232}.row{display:flex;gap:9px;flex-wrap:wrap;align-items:center;margin:9px 0}.row input{flex:1;min-width:130px}table{width:100%;border-collapse:collapse;margin-top:12px}th,td{text-align:left;padding:10px;border-bottom:1px solid #e5e9ee}th{background:#f5f7fa}.muted{color:#64748b;font-size:13px}.hidden{display:none}.msg{padding:10px;border-radius:5px;background:#eef4fa;margin:10px 0}.error{background:#fff0ef;color:#8a211b}.ok{background:#edf8ef;color:#205c2a}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}.tabs button{background:#526273}.tabs button.active{background:#1e5b87}.right{display:flex;gap:8px;align-items:center}.login{max-width:430px;margin:8vh auto}.login input{width:100%;margin:6px 0}.small{font-size:12px}@media(max-width:650px){table{font-size:13px}th,td{padding:7px}}
</style></head><body><header><h1>Controle de Almoxarifado</h1><div id="who" class="right"></div></header>
<main class="wrap"><section id="login" class="panel login"><h2>Acesso ao sistema</h2><form id="loginForm"><input name="username" placeholder="Usuário" required autocomplete="username"><input name="password" type="password" placeholder="Senha" required autocomplete="current-password"><button type="submit">Entrar</button></form><p class="muted">Primeiro acesso: admin / admin123 ou operador / operador123.</p><div id="loginMsg"></div><hr><h2>Criar conta de operador</h2><form id="registerForm"><input name="username" placeholder="Novo usuário" required minlength="3"><input name="password" type="password" placeholder="Senha (mínimo 6 caracteres)" required minlength="6"><button type="submit" class="secondary">Cadastrar</button></form></section>
<section id="app" class="hidden"><div class="tabs"><button data-tab="products" class="active">Produtos</button><button data-tab="movement">Movimentação</button><button data-tab="history">Histórico</button><button data-tab="users" id="usersTab">Usuários</button></div>
<section id="products" class="panel"><h2>Produtos e saldo</h2><form id="productForm" class="row"><input name="name" placeholder="Nome do produto" required><input name="quantity" type="number" min="0" placeholder="Saldo inicial" required><button>Adicionar produto</button></form><div class="row"><input id="filterName" placeholder="Filtrar por nome"><input id="filterDate" type="date"><button id="filterBtn" type="button">Filtrar</button><button id="clearBtn" class="secondary" type="button">Limpar</button></div><div id="productTable"></div><div class="row"><button id="prev" class="secondary">Anterior</button><span id="pageInfo" class="muted"></span><button id="next" class="secondary">Próxima</button></div></section>
<section id="movement" class="panel hidden"><h2>Registrar movimentação</h2><form id="movementForm"><div class="row"><select name="product_id" id="productSelect" required></select><select name="kind"><option value="entrada">Entrada</option><option value="saida">Saída</option></select><input name="quantity" type="number" min="1" placeholder="Quantidade" required><button>Registrar</button></div></form><p class="muted">A saída é bloqueada automaticamente quando o saldo é insuficiente.</p></section>
<section id="history" class="panel hidden"><h2>Histórico de movimentações</h2><div id="historyTable"></div></section>
<section id="users" class="panel hidden"><h2>Usuários cadastrados</h2><div id="usersTable"></div><p class="muted">Somente o administrador pode excluir usuários.</p></section></section><div id="globalMsg"></div></main>
<script>
const $=s=>document.querySelector(s);let page=1,role='',user='';
async function api(path,opts={}){let r=await fetch(path,{headers:{'Content-Type':'application/json'},...opts});let d=await r.json();if(!r.ok)throw Error(d.error||'Erro na operação');return d}
function message(el,msg,bad=false){el.innerHTML='<div class="msg '+(bad?'error':'ok')+'"></div>';el.firstChild.textContent=msg}
function formData(form){return Object.fromEntries(new FormData(form).entries())}
async function start(){try{let me=await api('/api/me');role=me.role;user=me.username;$('#login').classList.add('hidden');$('#app').classList.remove('hidden');$('#who').textContent=user+' — '+(role==='administrador'?'Administrador':'Operador');$('#usersTab').classList.toggle('hidden',role!=='administrador');await refresh();}catch(e){$('#login').classList.remove('hidden');$('#app').classList.add('hidden')}}
async function refresh(){await loadProducts();await loadHistory();await loadSelect();if(role==='administrador')await loadUsers()}
async function loadProducts(){let q=new URLSearchParams({page,name:$('#filterName').value,date:$('#filterDate').value});let d=await api('/api/products?'+q);$('#pageInfo').textContent=`Página ${d.page} de ${d.pages} — ${d.total} produto(s)`;$('#prev').disabled=page<=1;$('#next').disabled=page>=d.pages;$('#productTable').innerHTML='<table><thead><tr><th>Produto</th><th>Saldo</th><th>Atualizado em</th><th>Ações</th></tr></thead><tbody>'+d.items.map(p=>`<tr><td>${esc(p.name)}</td><td>${p.quantity}</td><td>${esc(p.updated_at)}</td><td><button class="secondary" onclick="editProduct(${p.id},'${esc(p.name).replaceAll("'","\\'")}',${p.quantity})">Editar</button> ${role==='administrador'?`<button class="danger" onclick="deleteProduct(${p.id})">Excluir</button>`:''}</td></tr>`).join('')+'</tbody></table>'}
function esc(v){return String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function loadSelect(){let d=await api('/api/products?page=1');$('#productSelect').innerHTML=d.items.map(p=>`<option value="${p.id}">${esc(p.name)} (saldo: ${p.quantity})</option>`).join('')}
async function loadHistory(){let d=await api('/api/movements');$('#historyTable').innerHTML='<table><tr><th>Data/hora</th><th>Produto</th><th>Tipo</th><th>Quantidade</th><th>Responsável</th></tr>'+d.items.map(m=>`<tr><td>${esc(m.created_at)}</td><td>${esc(m.product)}</td><td>${m.kind}</td><td>${m.quantity}</td><td>${esc(m.username)}</td></tr>`).join('')+'</table>'}
async function loadUsers(){let d=await api('/api/users');$('#usersTable').innerHTML='<table><tr><th>Usuário</th><th>Perfil</th><th>Ação</th></tr>'+d.items.map(u=>`<tr><td>${esc(u.username)}</td><td>${u.role}</td><td>${u.username===user?'Conta atual':`<button class="danger" onclick="deleteUser(${u.id})">Excluir</button>`}</td></tr>`).join('')+'</table>'}
window.editProduct=async(id,name,quantity)=>{let n=prompt('Nome do produto:',name);if(n===null)return;let q=prompt('Saldo (ajuste administrativo):',quantity);if(q===null)return;try{await api('/api/products/'+id,{method:'PUT',body:JSON.stringify({name:n,quantity:Number(q)})});await refresh();message($('#globalMsg'),'Produto atualizado.')}catch(e){message($('#globalMsg'),e.message,true)}};
window.deleteProduct=async id=>{if(!confirm('Excluir produto?'))return;try{await api('/api/products/'+id,{method:'DELETE'});await refresh()}catch(e){message($('#globalMsg'),e.message,true)}};
window.deleteUser=async id=>{if(!confirm('Excluir usuário?'))return;try{await api('/api/users/'+id,{method:'DELETE'});await loadUsers()}catch(e){message($('#globalMsg'),e.message,true)}};
$('#loginForm').onsubmit=async e=>{e.preventDefault();try{await api('/api/login',{method:'POST',body:JSON.stringify(formData(e.target))});e.target.reset();await start()}catch(err){message($('#loginMsg'),err.message,true)}};
$('#registerForm').onsubmit=async e=>{e.preventDefault();try{await api('/api/register',{method:'POST',body:JSON.stringify(formData(e.target))});message($('#loginMsg'),'Conta de operador criada. Faça login.');e.target.reset()}catch(err){message($('#loginMsg'),err.message,true)}};
$('#productForm').onsubmit=async e=>{e.preventDefault();let d=formData(e.target);try{await api('/api/products',{method:'POST',body:JSON.stringify({name:d.name,quantity:Number(d.quantity)})});e.target.reset();await refresh();message($('#globalMsg'),'Produto cadastrado.')}catch(err){message($('#globalMsg'),err.message,true)}};
$('#movementForm').onsubmit=async e=>{e.preventDefault();let d=formData(e.target);try{let r=await api('/api/movements',{method:'POST',body:JSON.stringify({...d,quantity:Number(d.quantity),product_id:Number(d.product_id)})});await refresh();message($('#globalMsg'),'Movimentação registrada. Novo saldo: '+r.quantity)}catch(err){message($('#globalMsg'),err.message,true)}};
$('#filterBtn').onclick=()=>{page=1;loadProducts()};$('#clearBtn').onclick=()=>{$('#filterName').value='';$('#filterDate').value='';page=1;loadProducts()};$('#prev').onclick=()=>{page--;loadProducts()};$('#next').onclick=()=>{page++;loadProducts()};
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x===b));['products','movement','history','users'].forEach(id=>$('#'+id).classList.toggle('hidden',id!==b.dataset.tab))});
start();
</script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print('%s - %s' % (self.log_date_time_string(), fmt % args))
    def send_json(self, data, status=200, headers=None):
        raw=json.dumps(data,ensure_ascii=False).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','no-store')
        for k,v in (headers or {}).items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(raw)
    def body(self):
        n=int(self.headers.get('Content-Length','0')); return json.loads(self.rfile.read(n) or b'{}')
    def current_user(self):
        cookie=SimpleCookie(self.headers.get('Cookie','')); morsel=cookie.get('session')
        return SESSIONS.get(morsel.value) if morsel else None
    def require(self, admin=False):
        u=self.current_user()
        if not u: self.send_json({'error':'Faça login para continuar.'},401); return None
        if admin and u['role']!='administrador': self.send_json({'error':'Acesso permitido somente ao administrador.'},403); return None
        return u
    def do_GET(self):
        path=urlparse(self.path).path; params=parse_qs(urlparse(self.path).query)
        if path=='/':
            raw=HTML.encode(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        if path=='/api/me':
            u=self.require();
            if u:self.send_json({'username':u['username'],'role':u['role']})
            return
        if path=='/api/products':
            if not self.require():return
            page=max(1,int(params.get('page',['1'])[0])); name=params.get('name',[''])[0].strip(); date=params.get('date',[''])[0]
            where=[]; vals=[]
            if name:where.append('name LIKE ?');vals.append('%'+name+'%')
            if date:where.append("date(updated_at)=?");vals.append(date)
            clause=(' WHERE '+' AND '.join(where)) if where else ''
            with connect() as db:
                total=db.execute('SELECT COUNT(*) FROM products'+clause,vals).fetchone()[0]; pages=max(1,(total+9)//10); page=min(page,pages)
                rows=db.execute('SELECT * FROM products'+clause+' ORDER BY name LIMIT 10 OFFSET ?',vals+[(page-1)*10]).fetchall()
            self.send_json({'items':[dict(x) for x in rows],'page':page,'pages':pages,'total':total});return
        if path=='/api/movements':
            if not self.require():return
            with connect() as db: rows=db.execute('SELECT m.*,p.name product FROM movements m JOIN products p ON p.id=m.product_id ORDER BY m.id DESC LIMIT 200').fetchall()
            self.send_json({'items':[dict(x) for x in rows]});return
        if path=='/api/users':
            if not self.require(admin=True):return
            with connect() as db: rows=db.execute('SELECT id,username,role,created_at FROM users ORDER BY username').fetchall()
            self.send_json({'items':[dict(x) for x in rows]});return
        self.send_json({'error':'Rota não encontrada.'},404)
    def do_POST(self):
        path=urlparse(self.path).path
        try:data=self.body()
        except Exception:self.send_json({'error':'Dados inválidos.'},400);return
        if path=='/api/login':
            with connect() as db: row=db.execute('SELECT * FROM users WHERE username=?',(str(data.get('username','')).strip(),)).fetchone()
            if not row or not check_password(str(data.get('password','')),row['password']):self.send_json({'error':'Usuário ou senha incorretos.'},401);return
            token=secrets.token_urlsafe(32);SESSIONS[token]={'id':row['id'],'username':row['username'],'role':row['role']}
            self.send_json({'ok':True}, headers={'Set-Cookie':f'session={token}; HttpOnly; SameSite=Strict; Path=/'})
            return
        if path=='/api/register':
            username=str(data.get('username','')).strip(); password=str(data.get('password',''))
            if len(username)<3 or len(password)<6:self.send_json({'error':'Usuário deve ter 3 caracteres e senha 6.'},400);return
            try:
                with connect() as db:db.execute('INSERT INTO users(username,password,role,created_at) VALUES(?,?,?,?)',(username,hash_password(password),'operador',datetime.now().astimezone().isoformat(timespec='seconds')))
                self.send_json({'ok':True},201)
            except sqlite3.IntegrityError:self.send_json({'error':'Esse usuário já existe.'},409)
            return
        u=self.require()
        if not u:return
        if path=='/api/products':
            name=str(data.get('name','')).strip(); qty=data.get('quantity')
            if not name or not isinstance(qty,int) or qty<0:self.send_json({'error':'Informe nome e saldo inicial válido.'},400);return
            now=datetime.now().astimezone().isoformat(timespec='seconds')
            with connect() as db:db.execute('INSERT INTO products(name,quantity,created_at,updated_at) VALUES(?,?,?,?)',(name,qty,now,now))
            self.send_json({'ok':True},201);return
        if path=='/api/movements':
            try:
                with connect() as db:
                    db.execute('BEGIN IMMEDIATE'); new=record_movement(db,int(data.get('product_id')),str(data.get('kind')),data.get('quantity'),u)
                self.send_json({'ok':True,'quantity':new},201)
            except (ValueError,TypeError,sqlite3.Error) as e:self.send_json({'error':str(e)},400)
            return
        self.send_json({'error':'Rota não encontrada.'},404)
    def do_PUT(self):
        u=self.require()
        if not u:return
        path=urlparse(self.path).path
        if not path.startswith('/api/products/'):self.send_json({'error':'Rota não encontrada.'},404);return
        try:pid=int(path.rsplit('/',1)[1]);data=self.body();name=str(data.get('name','')).strip();qty=data.get('quantity')
        except Exception:self.send_json({'error':'Dados inválidos.'},400);return
        if not name or not isinstance(qty,int) or qty<0:self.send_json({'error':'Nome e saldo válido são obrigatórios.'},400);return
        now=datetime.now().astimezone().isoformat(timespec='seconds')
        with connect() as db:
            old=db.execute('SELECT quantity FROM products WHERE id=?',(pid,)).fetchone()
            if not old:self.send_json({'error':'Produto não encontrado.'},404);return
            # Ajuste de saldo gera movimentação correspondente para manter rastreabilidade.
            delta=qty-old['quantity']; db.execute('UPDATE products SET name=?,quantity=?,updated_at=? WHERE id=?',(name,qty,now,pid))
            if delta:
                kind='entrada' if delta>0 else 'saida'; amount=abs(delta)
                db.execute('INSERT INTO movements(product_id,kind,quantity,user_id,username,created_at) VALUES(?,?,?,?,?,?)',(pid,kind,amount,u['id'],u['username'],now))
        self.send_json({'ok':True})
    def do_DELETE(self):
        path=urlparse(self.path).path
        if path.startswith('/api/products/'):
            if not self.require(admin=True):return
            try:pid=int(path.rsplit('/',1)[1])
            except ValueError:self.send_json({'error':'Identificador inválido.'},400);return
            with connect() as db:
                if db.execute('SELECT 1 FROM movements WHERE product_id=?',(pid,)).fetchone():self.send_json({'error':'Produto possui histórico e não pode ser excluído.'},409);return
                cur=db.execute('DELETE FROM products WHERE id=?',(pid,))
            self.send_json({'ok':True} if cur.rowcount else {'error':'Produto não encontrado.'},200 if cur.rowcount else 404);return
        if path.startswith('/api/users/'):
            if not self.require(admin=True):return
            try:uid=int(path.rsplit('/',1)[1])
            except ValueError:self.send_json({'error':'Identificador inválido.'},400);return
            if self.current_user()['id']==uid:self.send_json({'error':'Não é permitido excluir a própria conta.'},400);return
            with connect() as db:cur=db.execute('DELETE FROM users WHERE id=?',(uid,))
            self.send_json({'ok':True} if cur.rowcount else {'error':'Usuário não encontrado.'},200 if cur.rowcount else 404);return
        self.send_json({'error':'Rota não encontrada.'},404)

if __name__=='__main__':
    init_db(); host='127.0.0.1'; port=int(os.environ.get('PORT','8000'))
    print('Almoxarifado de Caio Pereira iniciado em http://%s:%s' % (host,port))
    print('Acesso inicial: admin/admin123 | operador/operador123')
    ThreadingHTTPServer((host,port),Handler).serve_forever()
