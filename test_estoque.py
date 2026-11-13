"""Testes automatizados da regra de saída de produtos (biblioteca unittest)."""
import os, tempfile, unittest
import app

class EstoqueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old=app.DB_PATH; app.DB_PATH=os.path.join(self.tmp.name,'teste.db'); app.init_db()
        with app.connect() as db:
            row=db.execute("SELECT id,username,role FROM users WHERE username='operador'").fetchone(); self.user=dict(row)
            now='2026-11-13T10:00:00-03:00'
            cur=db.execute('INSERT INTO products(name,quantity,created_at,updated_at) VALUES(?,?,?,?)',('Detergente',10,now,now)); self.pid=cur.lastrowid
    def tearDown(self):app.DB_PATH=self.old;self.tmp.cleanup()
    def test_01_saida_maior_que_saldo_bloqueada(self):
        with app.connect() as db:
            with self.assertRaisesRegex(ValueError,'Disponível: 10. Solicitado: 11'):
                app.record_movement(db,self.pid,'saida',11,self.user)
            self.assertEqual(db.execute('SELECT quantity FROM products WHERE id=?',(self.pid,)).fetchone()[0],10)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM movements').fetchone()[0],0)
    def test_02_saida_dentro_do_saldo_registrada(self):
        with app.connect() as db:
            saldo=app.record_movement(db,self.pid,'saida',4,self.user)
            self.assertEqual(saldo,6)
            mov=db.execute('SELECT * FROM movements').fetchone()
            self.assertEqual(mov['kind'],'saida');self.assertEqual(mov['quantity'],4);self.assertEqual(mov['username'],'operador');self.assertTrue(mov['created_at'])
    def test_03_saida_igual_ao_saldo_zerada(self):
        with app.connect() as db:
            saldo=app.record_movement(db,self.pid,'saida',10,self.user)
            self.assertEqual(saldo,0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM movements').fetchone()[0],1)

if __name__=='__main__':unittest.main(verbosity=2)
