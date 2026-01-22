import sqlite3
import firebase_admin
from firebase_admin import credentials, firestore

# 1. CONEXIÓN A FIREBASE
cred = credentials.Certificate("serviceAccountKey.json")
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db_fb = firestore.client()

# 2. CONEXIÓN A SQLITE (Tu archivo adjunto)
def migrar():
    try:
        conn = sqlite3.connect('inventario.db')
        conn.row_factory = sqlite3.Row  # Para leer por nombres de columna
        cursor = conn.cursor()

        print("🚀 Iniciando migración...")

        # --- MIGRAR TABLA 'equipos' ---
        cursor.execute("SELECT * FROM equipos")
        equipos = cursor.fetchall()
        print(f"📦 Procesando {len(equipos)} equipos activos...")
        
        for fila in equipos:
            datos = dict(fila)
            # Usamos el ID original de SQLite como nombre del documento en Firebase
            doc_id = str(datos.pop('id')) 
            db_fb.collection('equipos').document(doc_id).set(datos)

        # --- MIGRAR TABLA 'bajas' ---
        cursor.execute("SELECT * FROM bajas")
        bajas = cursor.fetchall()
        print(f"📄 Procesando {len(bajas)} registros de historial de bajas...")
        
        for fila in bajas:
            datos = dict(fila)
            # Para las bajas, dejamos que Firebase genere un ID único automático
            if 'id' in datos: datos.pop('id') 
            db_fb.collection('bajas').add(datos)

        print("✅ ¡Migración completada con éxito! Ya puedes ver tus datos en la consola de Firebase.")

    except Exception as e:
        print(f"❌ Error durante la migración: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    migrar()