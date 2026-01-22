import firebase_admin
from firebase_admin import credentials, firestore
from werkzeug.security import generate_password_hash
import os

# 1. CONFIGURAR LA CONEXIÓN (Igual que en app.py)
basedir = os.path.abspath(os.path.dirname(__file__))
ruta_json = os.path.join(basedir, 'serviceAccountKey.json')

if not firebase_admin._apps:
    cred = credentials.Certificate(ruta_json)
    firebase_admin.initialize_app(cred, {
        'databaseURL':'https://inventario-render-default-rtdb.firebaseio.com/'
    })

db = firestore.client()

# 2. CREAR EL USUARIO
try:
    # Generamos el hash de la contraseña 'admin123'
    hash_pw = generate_password_hash('admin123', method='pbkdf2:sha256')
    
    nuevo_usuario = {
        'username': 'admin',
        'password': hash_pw,
        'role': 'admin'
    }
    
    # Lo guardamos en la colección 'usuarios'
    db.collection('usuarios').add(nuevo_usuario)
    print("✅ ¡Usuario admin creado con éxito en Firebase!")
    print("👤 Usuario: admin")
    print("🔑 Contraseña: admin123")

except Exception as e:
    print(f"❌ Error al crear el usuario: {e}")