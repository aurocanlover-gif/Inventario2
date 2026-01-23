import os
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps
import os
import json
from firebase_admin import credentials, initialize_app

# 1. Definimos la ruta local (por si trabajas en tu PC)
ruta_json = 'serviceAccountKey.json'

if os.path.exists(ruta_json):
    # SI EL ARCHIVO EXISTE (Uso en tu computadora)
    cred = credentials.Certificate(ruta_json)
else:
    # SI EL ARCHIVO NO EXISTE (Uso en Render)
    firebase_json = os.environ.get('FIREBASE_JSON')
    if firebase_json:
        # Convertimos el texto de la variable en un diccionario real
        info_dict = json.loads(firebase_json)
        cred = credentials.Certificate(info_dict)
    else:
        raise ValueError("Error: No se encontró la variable FIREBASE_JSON en Render")
    if not firebase_admin._apps:
        initialize_app(cred, {
        'databaseURL': 'https://inventario-render-default-rtdb.firebaseio.com'
    })

# 2. Inicializamos la App una sola vez
initialize_app(cred)

# --- CONFIGURACIÓN DE LA APLICACIÓN ---
basedir = os.path.abspath(os.path.dirname(__file__))
template_dir = os.path.join(basedir, 'templates')

app = Flask(__name__, template_folder=template_dir)

# Clave secreta para sesiones (puedes dejar la que tenías o usar una fija)
app.secret_key = 'inventario_escolar_perote_2026' 

# --- CONFIGURACIÓN DE FIREBASE ---
# Buscamos el archivo JSON de credenciales que descargaste
ruta_json = os.path.join(basedir, 'serviceAccountKey.json')

if not firebase_admin._apps:
    cred = credentials.Certificate(ruta_json)
    firebase_admin.initialize_app(cred)

# Esta es nuestra conexión global a la base de datos
db = firestore.client()



ruta_json = os.path.join(basedir, 'serviceAccountKey.json')

if not firebase_admin._apps:
    cred = credentials.Certificate(ruta_json)
    firebase_admin.initialize_app(cred)

db = firestore.client()




# --- DECORADOR DE REQUERIMIENTO DE LOGIN ---
def login_required(f):
    @wraps(f) # Es mejor usar @wraps para que Flask no se confunda con los nombres de las funciones
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            flash('Debes iniciar sesión para acceder a esta página.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- RUTAS DE AUTENTICACIÓN ---

@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username_input = request.form['username']
        password_input = request.form['password']

        # Buscamos en la colección 'usuarios' de Firebase
        # .where() es el equivalente al WHERE de SQL
        usuarios_ref = db.collection('usuarios').where('username', '==', username_input).limit(1).get()

        if usuarios_ref:
            # Si existe, sacamos los datos del primer documento encontrado
            user_doc = usuarios_ref[0]
            user_data = user_doc.to_dict()

            if check_password_hash(user_data['password'], password_input):
                session['username'] = user_data['username']
                session['role'] = user_data.get('role', 'user') # 'user' por defecto si no tiene rol
                flash('Sesión iniciada correctamente.', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Contraseña incorrecta.', 'error')
        else:
            flash('Usuario no encontrado.', 'error')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear() # Borra toda la sesión de golpe, es más seguro
    flash('Sesión cerrada correctamente.', 'success')
    return redirect(url_for('login'))


# ==============================================================================
# RUTAS DE INVENTARIO (FIREBASE)
# ==============================================================================
@app.route('/dashboard')
@login_required
def dashboard():
    try:
        # 1. Obtenemos los parámetros de búsqueda y filtro
        filtro_tipo = request.args.get('tipo', '')
        busqueda = request.args.get('busqueda', '').lower().strip() # Capturamos la búsqueda
        
        equipos_ref = db.collection('equipos')
        
        # 2. Traemos los equipos activos
        query = equipos_ref.where('estado', '==', 'Activo')

        if filtro_tipo:
            query = query.where('equipo', '==', filtro_tipo)

        docs = query.stream()

        equipos_activos = []
        tipos_set = set()

        # 3. Procesamos los resultados con Filtro de Búsqueda Manual
        for doc in docs:
            item = doc.to_dict()
            item['id'] = doc.id
            
            # --- LÓGICA DE BÚSQUEDA (Case Insensitive) ---
            # Convertimos campos a minúsculas para comparar sin errores
            nombre = item.get('equipo', '').lower()
            marca = item.get('marca', '').lower()
            modelo = item.get('modelo', '').lower()
            serie = item.get('numero_serie', '').lower()
            inv_num = str(item.get('numero_inventario', '')).lower()

            # Si no hay búsqueda o si coincide con algún campo, lo agregamos
            if not busqueda or (busqueda in nombre or 
                                busqueda in marca or 
                                busqueda in modelo or
                                busqueda in serie or
                                busqueda in inv_num):
                equipos_activos.append(item)

        # 4. ORDENAR: Invertimos la lista para que el más nuevo salga primero
        # Nota: Como Firebase no garantiza orden sin un campo 'timestamp', invertimos la lista recibida
        equipos_activos.reverse()

        # 5. Traer tipos para el menú desplegable
        todas_las_opciones = equipos_ref.where('estado', '==', 'Activo').stream()
        for d in todas_las_opciones:
            datos = d.to_dict()
            if 'equipo' in datos and datos['equipo']:
                tipos_set.add(datos['equipo'])

        return render_template('dashboard.html', 
                               equipos=equipos_activos, 
                               tipos_disponibles=sorted(list(tipos_set)),
                               filtro_tipo=filtro_tipo)
    
    except Exception as e:
        print(f"Error real en dashboard: {e}")
        return render_template('dashboard.html', equipos=[], tipos_disponibles=[], filtro_tipo='')

@app.route('/agregar', methods=['GET', 'POST'])
@login_required
def agregar_equipo():
    if request.method == 'POST':
        try:
            num_inv = request.form['numero_inventario'].strip().upper()
            
            # Verificar si el número de inventario ya existe en Firebase
            existe = db.collection('equipos').where('numero_inventario', '==', num_inv).limit(1).get()
            if existe:
                flash(f'Error: El Número de Inventario {num_inv} ya existe.', 'error')
                return redirect(url_for('agregar_equipo'))

            data = {
                'numero_inventario': num_inv,
                'equipo': request.form['equipo'].strip(),
                'marca': request.form.get('marca', '').strip(),
                'modelo': request.form.get('modelo', '').strip(),
                'numero_serie': request.form.get('numero_serie', '').strip(),
                'departamento': request.form['departamento'].strip(),
                'nombre': request.form.get('nombre', '').strip(),
                'ubicacion': request.form.get('ubicacion', '').strip(),
                'revisar': request.form.get('revisar', '').strip(),
                'observaciones': request.form.get('observaciones', '').strip(),
                'estado': 'Activo',
                'fecha_registro': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

            # Guardar en Firebase
            db.collection('equipos').add(data)
            flash(f'Equipo {num_inv} registrado exitosamente.', 'success')
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            flash(f'Error al guardar en la nube: {e}', 'error')
            
    return render_template('agregar_equipo.html')
@app.route('/editar/<equipo_id>', methods=['GET', 'POST'])
@login_required
def editar_equipo(equipo_id):
    # 1. Buscamos el equipo por su ID único de Firebase
    equipo_ref = db.collection('equipos').document(equipo_id)
    doc = equipo_ref.get()

    if not doc.exists:
        flash('Error: El equipo no existe.', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        try:
            # 2. Recogemos los datos actualizados del formulario
            datos_actualizados = {
                'numero_inventario': request.form['numero_inventario'].strip().upper(),
                'equipo': request.form['equipo'].strip(),
                'marca': request.form.get('marca', '').strip(),
                'modelo': request.form.get('modelo', '').strip(),
                'numero_serie': request.form.get('numero_serie', '').strip(),
                'departamento': request.form['departamento'].strip(),
                'nombre': request.form.get('nombre', '').strip(),
                'ubicacion': request.form.get('ubicacion', '').strip(), # Aquí cambias el lugar
                'revisar': request.form.get('revisar', '').strip(),
                'observaciones': request.form.get('observaciones', '').strip(),
                'estado': request.form.get('estado', 'Activo')
            }

            # 3. Guardamos los cambios en Firebase
            equipo_ref.update(datos_actualizados)
            flash(f'Equipo {datos_actualizados["numero_inventario"]} actualizado correctamente.', 'success')
            return redirect(url_for('dashboard'))

        except Exception as e:
            flash(f'Error al actualizar: {e}', 'error')

    # Si es GET, mostramos el formulario con los datos actuales
    return render_template('editar_equipo.html', equipo=doc.to_dict(), equipo_id=doc.id)

@app.route('/baja', methods=['GET', 'POST'])
@login_required
def registrar_baja():
    if request.method == 'POST':
        numero_inv = request.form['numero_inventario'].strip().upper()
        motivo = request.form['motivo'].strip()
        fecha_actual = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        try:
            # 1. Buscar el equipo activo
            equipo_query = db.collection('equipos').where('numero_inventario', '==', numero_inv).limit(1).get()
            
            if not equipo_query:
                flash(f'Error: Equipo {numero_inv} no encontrado.', 'error')
                return redirect(url_for('registrar_baja'))
            
            doc_equipo = equipo_query[0]
            datos_equipo = doc_equipo.to_dict()

            if datos_equipo.get('estado') == 'Baja':
                flash(f'El equipo {numero_inv} ya está de baja.', 'warning')
                return redirect(url_for('ver_bajas'))

            # 2. Registrar en la colección 'bajas' (Historial)
            datos_baja = datos_equipo.copy()
            datos_baja.update({
                'motivo_baja': motivo,
                'fecha_baja': fecha_actual,
                'fecha_registro_original': datos_equipo.get('fecha_registro'),
                'equipo_id_referencia': doc_equipo.id
            })
            # Firebase usa 'inventario' en tu tabla de bajas según tu código anterior
            datos_baja['inventario'] = datos_equipo['numero_inventario']
            
            db.collection('bajas').add(datos_baja)

            # 3. Actualizar estado en la colección 'equipos'
            db.collection('equipos').document(doc_equipo.id).update({
                'estado': 'Baja',
                'motivo_baja': motivo,
                'fecha_baja': fecha_actual
            })
            
            flash(f'Equipo {numero_inv} dado de baja exitosamente.', 'success')
            return redirect(url_for('ver_bajas'))

        except Exception as e:
            flash(f'Error en el proceso de baja: {e}', 'error')

    return render_template('baja.html')

@app.route('/consulta', methods=['GET', 'POST'])
@login_required
def consulta():
    equipo = None
    error = None
    if request.method == 'POST':
        num_inv = request.form['numero_inventario'].strip().upper()
        # Buscamos en la nube
        res = db.collection('equipos').where('numero_inventario', '==', num_inv).limit(1).get()
        
        if res:
            equipo = res[0].to_dict()
            equipo['id'] = res[0].id
        else:
            error = f"No se encontró el inventario: {num_inv}"
        
        return render_template('resultado_busqueda.html', equipo=equipo, error=error)

    return render_template('consulta.html')
@app.route('/bajas')
@login_required
def ver_bajas():
    """Ruta para ver el historial de bajas desde Firebase."""
    try:
        # Traemos todos los documentos de la colección 'bajas'
        bajas_ref = db.collection('bajas').order_by('fecha_baja', direction=firestore.Query.DESCENDING).stream()
        
        lista_bajas = []
        for doc in bajas_ref:
            item = doc.to_dict()
            item['id'] = doc.id  # Usamos el ID de Firebase para poder eliminar si es necesario
            lista_bajas.append(item)
            
        return render_template('ver_bajas.html', bajas=lista_bajas)
    except Exception as e:
        print(f"Error al cargar bajas: {e}")
        return render_template('ver_bajas.html', bajas=[])

@app.route('/eliminar/<equipo_id>', methods=['POST'])
@login_required
def eliminar_equipo(equipo_id):
    """Elimina un equipo de la colección 'equipos'."""
    if session.get('role') != 'admin':
        flash('Solo administradores pueden eliminar.', 'error')
        return redirect(url_for('dashboard'))

    try:
        # En Firebase, eliminar es así de simple:
        db.collection('equipos').document(equipo_id).delete()
        flash('Registro eliminado permanentemente de la nube.', 'success')
    except Exception as e:
        flash(f'Error al eliminar: {e}', 'error')
        
    return redirect(url_for('dashboard'))

@app.route('/eliminar_baja/<baja_id>', methods=['POST'])
@login_required
def eliminar_baja(baja_id):
    """Elimina un registro del historial de bajas."""
    if session.get('role') != 'admin':
        flash('Solo administradores pueden eliminar historial.', 'error')
        return redirect(url_for('ver_bajas'))

    try:
        db.collection('bajas').document(baja_id).delete()
        flash('Registro de historial eliminado.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'error')
        
    return redirect(url_for('ver_bajas'))
if __name__ == '__main__':
    app.run(debug=True)