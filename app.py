import sqlite3
import secrets
import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# --- CONFIGURACIÓN DE LA APLICACIÓN ---
# Configurar la ruta base del proyecto
basedir = os.path.abspath(os.path.dirname(__file__))
template_dir = os.path.join(basedir, 'templates')

app = Flask(__name__, template_folder=template_dir)
# Genera una clave secreta fuerte para la gestión de sesiones
app.secret_key = secrets.token_hex(16) 
DATABASE = 'inventario.db'

# --- FUNCIONES DE BASE DE DATOS ---

def get_db():
    """Obtiene la conexión a la base de datos, si no existe, la crea y la almacena en g."""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    """Cierra la conexión a la base de datos al finalizar la solicitud."""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    """
    Inicializa la base de datos y realiza migraciones de esquema
    para asegurar que todas las columnas necesarias existan, conservando los datos.
    """
    with app.app_context():
        db = get_db()
        cursor = db.cursor()

        # 1. Tabla de Usuarios (Si no existe)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL
            )
        ''')

        # 2. Tabla de Equipos (Creación inicial con el esquema completo)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS equipos (
                id INTEGER PRIMARY KEY,
                numero_inventario TEXT UNIQUE NOT NULL,
                equipo TEXT NOT NULL,
                marca TEXT,
                modelo TEXT,
                numero_serie TEXT,
                departamento TEXT NOT NULL,
                nombre TEXT,
                ubicacion TEXT,
                revisar TEXT,
                observaciones TEXT,
                estado TEXT NOT NULL,
                fecha_registro TEXT,
                fecha_baja TEXT,
                motivo_baja TEXT
            )
        ''')
        
        # --- LÓGICA DE MIGRACIÓN DE ESQUEMA (CONSERVACIÓN DE DATOS) ---
        
        # Función auxiliar para obtener la lista actual de columnas
        def get_current_columns():
            try:
                return [info[1] for info in db.execute("PRAGMA table_info(equipos)").fetchall()]
            except:
                return []

        # MIGRACIÓN 1: Renombrar 'nombre_responsable' a 'nombre'
        try:
            if 'nombre_responsable' in get_current_columns():
                db.execute("ALTER TABLE equipos RENAME COLUMN nombre_responsable TO nombre")
                db.commit()
        except sqlite3.OperationalError:
            pass # Ignorar si la columna no existe

        # MIGRACIÓN 2: Añadir columna 'estado'
        try:
            if 'estado' not in get_current_columns():
                # Añadir columna con valor por defecto 'Activo' para registros antiguos
                db.execute("ALTER TABLE equipos ADD COLUMN estado TEXT NOT NULL DEFAULT 'Activo'")
                db.commit()
        except sqlite3.OperationalError:
            pass

        # MIGRACIÓN 3: Añadir columna 'fecha_baja'
        try:
            if 'fecha_baja' not in get_current_columns():
                db.execute("ALTER TABLE equipos ADD COLUMN fecha_baja TEXT")
                db.commit()
        except sqlite3.OperationalError:
            pass

        # MIGRACIÓN 4: Añadir columna 'motivo_baja'
        try:
            if 'motivo_baja' not in get_current_columns():
                db.execute("ALTER TABLE equipos ADD COLUMN motivo_baja TEXT")
                db.commit()
        except sqlite3.OperationalError:
            pass

        # MIGRACIÓN 5: Añadir columna 'fecha_registro'
        try:
            if 'fecha_registro' not in get_current_columns():
                # Asignar una fecha por defecto (hoy) a los registros antiguos para permitir la ordenación
                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                db.execute(f"ALTER TABLE equipos ADD COLUMN fecha_registro TEXT DEFAULT '{now}'")
                db.commit()
        except sqlite3.OperationalError:
            pass
             # MIGRACIÓN 6: Añadir la columna 'revisar' (FALTANTE)
        try:
            if 'revisar' not in get_current_columns():
                # Esta es la migración que resuelve el error reportado por el usuario
                db.execute("ALTER TABLE equipos ADD COLUMN revisar TEXT")
                db.commit()
        except sqlite3.OperationalError:
            pass
        try:
            if 'observaciones' not in get_current_columns():
                # Esta es la migración que resuelve el error reportado por el usuario
                db.execute("ALTER TABLE equipos ADD COLUMN observaciones TEXT")
                db.commit()
        except sqlite3.OperationalError:
            pass
        
        # 3. Tabla de Bajas (Migración para corregir estructura)
        try:
            # Función para obtener columnas de una tabla
            def get_table_columns(table_name):
                try:
                    return [info[1] for info in db.execute(f"PRAGMA table_info({table_name})").fetchall()]
                except:
                    return []
            
            # Si la tabla bajas no existe, la creamos con estructura completa
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bajas (
                    id INTEGER PRIMARY KEY,
                    equipo_id INTEGER,
                    numero_inventario TEXT NOT NULL,
                    equipo TEXT NOT NULL,
                    marca TEXT,
                    modelo TEXT,
                    numero_serie TEXT,
                    departamento TEXT NOT NULL,
                    nombre TEXT,
                    ubicacion TEXT,
                    revisar TEXT,
                    observaciones TEXT,
                    motivo_baja TEXT NOT NULL,
                    fecha_baja TEXT NOT NULL,
                    fecha_registro_original TEXT
                )
            ''')
            
            # Verificar estructura actual de la tabla bajas
            bajas_columns = get_table_columns('bajas')
            table_info = db.execute("PRAGMA table_info(bajas)").fetchall()
            
            # Detectar columnas problemáticas (PRIMARY KEY que no sean INTEGER)
            columnas_problematicas = []
            tiene_id_numerico = False
            
            for col_info in table_info:
                col_name = col_info[1]
                col_type = col_info[2]
                is_pk = col_info[5] == 1
                
                # Si es PRIMARY KEY y NO es INTEGER, es problemática
                if is_pk and col_type.upper() != 'INTEGER':
                    columnas_problematicas.append(col_name)
                # También detectar columnas con nombres comunes de ID que no sean INTEGER
                elif col_name.lower() in ['id_baja', 'idbaja', 'baja_id'] and col_type.upper() != 'INTEGER':
                    columnas_problematicas.append(col_name)
                elif col_name.lower() == 'id' and col_type.upper() == 'INTEGER' and is_pk:
                    tiene_id_numerico = True
            
            # Si hay columnas problemáticas (especialmente si alguna es PRIMARY KEY), hacer migración
            # Esto asegura que siempre tengamos una PRIMARY KEY INTEGER
            pk_problematica = any(info[5] == 1 and info[2].upper() != 'INTEGER' for info in table_info)
            
            if (columnas_problematicas and not tiene_id_numerico) or pk_problematica:
                # Crear nueva tabla con estructura correcta
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS bajas_new (
                        id INTEGER PRIMARY KEY,
                        equipo_id INTEGER,
                        numero_inventario TEXT NOT NULL,
                        equipo TEXT NOT NULL,
                        marca TEXT,
                        modelo TEXT,
                        numero_serie TEXT,
                        departamento TEXT NOT NULL,
                        nombre TEXT,
                        ubicacion TEXT,
                        revisar TEXT,
                        observaciones TEXT,
                        motivo_baja TEXT NOT NULL,
                        fecha_baja TEXT NOT NULL,
                        fecha_registro_original TEXT
                    )
                ''')
                
                # Obtener todas las columnas que NO son problemáticas de la tabla antigua
                columnas_validas_antigua = [col for col in bajas_columns if col not in columnas_problematicas and col != 'id']
                
                # Mapeo de nombres de columnas comunes (tabla antigua -> tabla nueva)
                # Este mapeo busca en TODAS las columnas de la tabla antigua, no solo las válidas
                mapeo_columnas_completo = {
                    # Nombres exactos
                    'equipo_id': 'equipo_id',
                    'numero_inventario': 'numero_inventario',
                    'equipo': 'equipo',
                    'marca': 'marca',
                    'modelo': 'modelo',
                    'numero_serie': 'numero_serie',
                    'departamento': 'departamento',
                    'nombre': 'nombre',
                    'ubicacion': 'ubicacion',
                    'revisar': 'revisar',
                    'observaciones': 'observaciones',
                    'motivo_baja': 'motivo_baja',
                    'fecha_baja': 'fecha_baja',
                    'fecha_registro_original': 'fecha_registro_original',
                    # Variaciones comunes encontradas en la BD real
                    'num_inventario': 'numero_inventario',
                    'inventario': 'numero_inventario',
                    'num_serie': 'numero_serie',
                    'serie': 'numero_serie',
                    'depto': 'departamento',
                    'departamento_responsable': 'departamento',
                    'responsable': 'nombre',
                    'nombre_responsable': 'nombre',
                    'motivo': 'motivo_baja',  # IMPORTANTE: motivo -> motivo_baja
                    'razon_baja': 'motivo_baja',
                    'razon': 'motivo_baja',
                    'fecha_registro': 'fecha_registro_original',  # IMPORTANTE: fecha_registro -> fecha_registro_original
                    'fecha_ingreso': 'fecha_registro_original',
                    'fechaRegistro': 'fecha_registro_original',
                    'id_equipo': 'equipo_id',
                    'equipoid': 'equipo_id',
                }
                
                # Leer todos los datos de la tabla antigua
                datos_antiguos = db.execute('SELECT * FROM bajas').fetchall()
                
                # Mostrar información de depuración
                if datos_antiguos:
                    print(f"Migrando {len(datos_antiguos)} registros de la tabla bajas...")
                    # Mostrar las columnas disponibles en el primer registro
                    primer_registro = dict(datos_antiguos[0])
                    print(f"Columnas encontradas en tabla antigua: {list(primer_registro.keys())}")
                
                # Migrar cada fila individualmente
                for idx, row_antigua in enumerate(datos_antiguos):
                    row_dict = dict(row_antigua)
                    
                    # Preparar valores para la nueva tabla
                    valores_insert = {}
                    
                    # Columnas que esperamos en la nueva tabla
                    columnas_nueva = [
                        'equipo_id', 'numero_inventario', 'equipo', 'marca', 'modelo',
                        'numero_serie', 'departamento', 'nombre', 'ubicacion', 'revisar',
                        'observaciones', 'motivo_baja', 'fecha_baja', 'fecha_registro_original'
                    ]
                    
                    # Valores por defecto para columnas NOT NULL
                    valores_default = {
                        'numero_inventario': 'N/A',
                        'equipo': 'No especificado',
                        'departamento': 'No especificado',
                        'motivo_baja': 'No especificado',
                        'fecha_baja': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    
                    for col_nueva in columnas_nueva:
                        # Buscar en el diccionario de la fila antigua
                        valor = None
                        
                        # Primero buscar por nombre exacto en row_dict
                        if col_nueva in row_dict:
                            valor = row_dict[col_nueva]
                        else:
                            # Buscar en el mapeo completo (buscar en TODAS las columnas de la tabla antigua)
                            for col_antigua, col_destino in mapeo_columnas_completo.items():
                                if col_destino == col_nueva and col_antigua in row_dict:
                                    valor = row_dict[col_antigua]
                                    break
                        
                        # Si encontramos un valor y no es None, usarlo
                        if valor is not None and valor != '':
                            valores_insert[col_nueva] = valor
                        # Si es una columna NOT NULL y no tenemos valor, usar default
                        elif col_nueva in valores_default:
                            valores_insert[col_nueva] = valores_default[col_nueva]
                        # Si es opcional y no tenemos valor, no incluirla (será NULL)
                        elif valor is None or valor == '':
                            pass  # No incluir columnas opcionales vacías
                    
                    # Asegurar que tenemos los campos obligatorios (NOT NULL)
                    campos_obligatorios = ['numero_inventario', 'equipo', 'departamento', 'motivo_baja', 'fecha_baja']
                    for campo in campos_obligatorios:
                        if campo not in valores_insert:
                            valores_insert[campo] = valores_default.get(campo, 'No especificado')
                    
                    # Insertar (ahora tenemos garantizado que todos los campos NOT NULL están presentes)
                    if valores_insert:
                        columnas = list(valores_insert.keys())
                        valores = [valores_insert[col] for col in columnas]
                        placeholders = ', '.join(['?'] * len(columnas))
                        
                        try:
                            cursor.execute(f'''
                                INSERT INTO bajas_new ({', '.join(columnas)})
                                VALUES ({placeholders})
                            ''', valores)
                        except sqlite3.IntegrityError as e:
                            # Si aún hay error, registrar pero continuar con el siguiente registro
                            print(f"Error al migrar registro {idx+1}: {e}. Datos: {valores_insert}")
                            continue
                
                if datos_antiguos:
                    print(f"Migración completada. {len(datos_antiguos)} registros procesados.")
                
                # Verificar cuántos registros se migraron
                registros_migrados = cursor.rowcount if hasattr(cursor, 'rowcount') else len(datos_antiguos)
                
                # Eliminar tabla vieja
                cursor.execute('DROP TABLE bajas')
                
                # Renombrar nueva tabla
                cursor.execute('ALTER TABLE bajas_new RENAME TO bajas')
                
                db.commit()
                
                # Verificar que los datos se migraron correctamente
                registros_nueva = db.execute('SELECT COUNT(*) FROM bajas').fetchone()[0]
                if registros_nueva == 0 and len(datos_antiguos) > 0:
                    print(f"ADVERTENCIA: Se intentaron migrar {len(datos_antiguos)} registros pero la nueva tabla está vacía.")
                    
            # Si ya existe id numérico pero hay columnas problemáticas, eliminarlas mediante migración
            elif columnas_problematicas and tiene_id_numerico:
                # Crear nueva tabla sin las columnas problemáticas
                columnas_validas = [col for col in bajas_columns if col not in columnas_problematicas]
                
                if columnas_validas:
                    columnas_def = []
                    for col_info in table_info:
                        col_name = col_info[1]
                        col_type = col_info[2]
                        is_pk = col_info[5] == 1
                        
                        if col_name not in columnas_problematicas:
                            pk_str = ' PRIMARY KEY' if is_pk else ''
                            columnas_def.append(f'{col_name} {col_type}{pk_str}')
                    
                    # Crear nueva tabla
                    cursor.execute(f'''
                        CREATE TABLE IF NOT EXISTS bajas_new (
                            {', '.join(columnas_def)}
                        )
                    ''')
                    
                    # Migrar datos
                    columnas_select = ', '.join(columnas_validas)
                    columnas_insert = ', '.join(columnas_validas)
                    
                    cursor.execute(f'''
                        INSERT INTO bajas_new ({columnas_insert})
                        SELECT {columnas_select} FROM bajas
                    ''')
                    
                    # Eliminar tabla vieja y renombrar
                    cursor.execute('DROP TABLE bajas')
                    cursor.execute('ALTER TABLE bajas_new RENAME TO bajas')
                    db.commit()
            
            # Verificar y agregar columnas faltantes
            bajas_columns = get_table_columns('bajas')
            columnas_requeridas = {
                'equipo_id': 'INTEGER',
                'fecha_registro_original': 'TEXT',
                'revisar': 'TEXT',
                'observaciones': 'TEXT'
            }
            
            for col_name, col_type in columnas_requeridas.items():
                if col_name not in bajas_columns:
                    try:
                        db.execute(f"ALTER TABLE bajas ADD COLUMN {col_name} {col_type}")
                        db.commit()
                    except sqlite3.OperationalError:
                        pass  # Ignorar si la columna ya existe o hay error
                        
        except sqlite3.OperationalError as e:
            pass  # Si hay error, la tabla probablemente ya existe con su propia estructura
        
        # Inserta el usuario administrador por defecto si no existe
        hashed_password = generate_password_hash('admin123', method='pbkdf2:sha256')
        try:
            cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                            ('admin', hashed_password, 'admin'))
            db.commit()
        except sqlite3.IntegrityError:
            pass

        db.commit()

# Llama a la inicialización al inicio
init_db()

# --- DECORADOR DE REQUERIMIENTO DE LOGIN ---

def login_required(f):
    # Decorador para proteger rutas
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            flash('Debes iniciar sesión para acceder a esta página.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# --- RUTAS DE AUTENTICACIÓN ---

@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

        if user:
            if check_password_hash(user['password'], password):
                session['username'] = user['username']
                session['role'] = user['role']
                flash('Sesión iniciada correctamente.', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Contraseña incorrecta.', 'error')
        else:
            flash('Usuario no encontrado.', 'error')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('role', None)
    flash('Sesión cerrada correctamente.', 'success')
    return redirect(url_for('login'))

# --- RUTAS DE INVENTARIO ---

@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    
    filtro_tipo = request.args.get('tipo', '')
    
    # Consulta equipos activos
    query = 'SELECT * FROM equipos WHERE estado = "Activo"'
    params = []

    if filtro_tipo:
        query += ' AND equipo = ?'
        params.append(filtro_tipo)
        
    query += ' ORDER BY fecha_registro DESC'
    
    equipos_activos = db.execute(query, params).fetchall()

    tipos_disponibles = db.execute('SELECT DISTINCT equipo FROM equipos ORDER BY equipo ASC').fetchall()
    tipos_disponibles = [t[0] for t in tipos_disponibles]

    return render_template('dashboard.html', 
                            equipos=equipos_activos, 
                            tipos_disponibles=tipos_disponibles,
                            filtro_tipo=filtro_tipo)


@app.route('/agregar', methods=['GET', 'POST'])
@login_required
def agregar_equipo():
    if request.method == 'POST':
        try:
            data = {
                'numero_inventario': request.form['numero_inventario'].strip().upper(),
                'equipo': request.form['equipo'].strip(),
                'marca': request.form.get('marca', '').strip(),
                'modelo': request.form.get('modelo', '').strip(),
                'numero_serie': request.form.get('numero_serie', '').strip(),
                'departamento': request.form['departamento'].strip(),
                'nombre': request.form.get('nombre', '').strip(),
                # Asumiendo que has agregado 'ubicacion' y 'revisar' al formulario, si no existen se insertarán como NULL
                'ubicacion': request.form.get('ubicacion', '').strip(),
                'revisar': request.form.get('revisar', '').strip(),
                'observaciones': request.form.get('observaciones', '').strip(),
                'estado': 'Activo',
                'fecha_registro': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

            db = get_db()
            cursor = db.cursor()
            
            cursor.execute('''
                INSERT INTO equipos (numero_inventario, equipo, marca, modelo, numero_serie, 
                                     departamento, nombre, ubicacion, revisar, observaciones, estado, fecha_registro) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (data['numero_inventario'], data['equipo'], data['marca'], data['modelo'], 
                  data['numero_serie'], data['departamento'], data['nombre'], 
                  data['ubicacion'], data['revisar'], data['observaciones'],
                  data['estado'], data['fecha_registro']))

            db.commit()
            flash(f'Equipo {data["numero_inventario"]} registrado exitosamente como ACTIVO.', 'success')
            return redirect(url_for('dashboard'))
            
        except sqlite3.IntegrityError:
            flash(f'Error: El Número de Inventario {data["numero_inventario"]} ya existe.', 'error')
        except Exception as e:
            flash(f'Ocurrió un error al guardar: {e}', 'error')
            
    return render_template('agregar_equipo.html')


@app.route('/baja', methods=['GET', 'POST'])
@login_required
def registrar_baja():
    """Ruta para marcar un equipo como 'Baja' y registrarlo en la tabla 'bajas'."""
    if request.method == 'POST':
        numero_inventario = request.form['numero_inventario'].strip().upper()
        motivo = request.form['motivo'].strip()
        fecha_baja = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        db = get_db()
        cursor = db.cursor()
        
        # 1. Verificar si el equipo existe y no está ya de baja
        equipo = db.execute('SELECT * FROM equipos WHERE numero_inventario = ?', (numero_inventario,)).fetchone()
        
        if not equipo:
            flash(f'Error: El equipo {numero_inventario} no fue encontrado en el inventario.', 'error')
        elif equipo['estado'] == 'Baja':
            flash(f'Error: El equipo {numero_inventario} ya está registrado como BAJA.', 'warning')
        else:
            try:
                # Verificar si ya existe en la tabla bajas (usar numero_inventario, no id)
                baja_existente = db.execute(
                    'SELECT numero_inventario FROM bajas WHERE numero_inventario = ?',
                    (numero_inventario,)
                ).fetchone()
                
                if baja_existente:
                    flash(f'Error: El equipo {numero_inventario} ya existe en la tabla de bajas.', 'warning')
                    return redirect(url_for('ver_bajas'))
                
                # Función auxiliar para obtener valores de Row objects
                def get_val(row, key, default=None):
                    try:
                        val = row[key]
                        return val if val is not None else default
                    except (KeyError, IndexError):
                        return default
                
                # Obtener columnas de la tabla bajas y detectar clave primaria
                table_info = db.execute("PRAGMA table_info(bajas)").fetchall()
                bajas_columns = [info[1] for info in table_info]
                
                # Encontrar la columna PRIMARY KEY (id autoincremental)
                pk_column = None
                for info in table_info:
                    if info[5] == 1:  # pk es el índice 5
                        pk_column = info[1]
                        break
                
                # Preparar datos para insertar (solo columnas que existen)
                datos_equipo = {
                    'equipo_id': equipo['id'],
                    'numero_inventario': equipo['numero_inventario'],
                    'equipo': equipo['equipo'],
                    'marca': get_val(equipo, 'marca'),
                    'modelo': get_val(equipo, 'modelo'),
                    'numero_serie': get_val(equipo, 'numero_serie'),
                    'departamento': equipo['departamento'],
                    'nombre': get_val(equipo, 'nombre'),
                    'ubicacion': get_val(equipo, 'ubicacion'),
                    'revisar': get_val(equipo, 'revisar'),
                    'observaciones': get_val(equipo, 'observaciones'),
                    'motivo_baja': motivo,
                    'fecha_baja': fecha_baja,
                    'fecha_registro_original': get_val(equipo, 'fecha_registro')
                }
                
                # Filtrar columnas que existen y excluir la clave primaria autoincremental
                columnas_disponibles = [
                    col for col in datos_equipo.keys() 
                    if col in bajas_columns and col != pk_column
                ]
                valores = [datos_equipo[col] for col in columnas_disponibles]
                
                # Construir y ejecutar INSERT dinámico
                columnas_str = ', '.join(columnas_disponibles)
                placeholders = ', '.join(['?'] * len(columnas_disponibles))
                
                cursor.execute(f'''
                    INSERT INTO bajas ({columnas_str})
                    VALUES ({placeholders})
                ''', valores)
                
                # 3. Actualizar el estado del equipo en la tabla equipos
                cursor.execute('''
                    UPDATE equipos
                    SET estado = ?, motivo_baja = ?, fecha_baja = ?
                    WHERE numero_inventario = ?
                ''', ('Baja', motivo, fecha_baja, numero_inventario))
                
                db.commit()
                flash(f'Equipo {numero_inventario} dado de BAJA exitosamente. Motivo: {motivo}', 'success')
                return redirect(url_for('ver_bajas'))
            except Exception as e:
                db.rollback()
                flash(f'Ocurrió un error al registrar la baja: {e}', 'error')

    return render_template('baja.html')


@app.route('/consulta', methods=['GET', 'POST'])
@login_required
def consulta():
    equipo = None
    error = None
    
    if request.method == 'POST':
        numero_inventario = request.form['numero_inventario'].strip().upper()
        
        db = get_db()
        # Busca el equipo en la única tabla, que tiene el campo 'estado'
        equipo = db.execute('SELECT * FROM equipos WHERE numero_inventario = ?', 
                            (numero_inventario,)).fetchone()
                            
        if not equipo:
            error = f"No se encontró ningún equipo con el Número de Inventario: {numero_inventario}"
        
        return render_template('resultado_busqueda.html', equipo=equipo, error=error)

    return render_template('consulta.html')


@app.route('/bajas')
@login_required
def ver_bajas():
    """Ruta para ver el listado de equipos dados de baja desde la tabla 'bajas'."""
    db = get_db()
    
    # Verificar qué columnas tiene la tabla bajas y encontrar la clave primaria
    try:
        table_info = db.execute("PRAGMA table_info(bajas)").fetchall()
        bajas_columns = [info[1] for info in table_info]
        
        # Encontrar la clave primaria (columna con pk=1)
        primary_key = None
        for info in table_info:
            if info[5] == 1:  # pk es el índice 5 en PRAGMA table_info
                primary_key = info[1]
                break
        
        # Si no encontramos pk, buscar por nombres comunes
        if not primary_key:
            for col_name in ['id', 'ID', 'Id', '_id']:
                if col_name in bajas_columns:
                    primary_key = col_name
                    break
        
        # Si existe fecha_baja, ordenar por ella, sino ordenar por clave primaria
        if 'fecha_baja' in bajas_columns:
            bajas_raw = db.execute('SELECT * FROM bajas ORDER BY fecha_baja DESC').fetchall()
        elif primary_key:
            bajas_raw = db.execute(f'SELECT * FROM bajas ORDER BY {primary_key} DESC').fetchall()
        else:
            bajas_raw = db.execute('SELECT * FROM bajas').fetchall()
            
        # Convertir Row objects a diccionarios y agregar el id extraído
        bajas = []
        for row in bajas_raw:
            row_dict = dict(row)
            # Agregar 'id' como alias de la clave primaria si existe
            if primary_key and primary_key in row_dict:
                row_dict['id'] = row_dict[primary_key]
            bajas.append(row_dict)
            
    except Exception as e:
        # Si hay error, intentar consulta simple
        primary_key = 'id'  # Default
        bajas_raw = db.execute('SELECT * FROM bajas').fetchall()
        bajas = [dict(row) for row in bajas_raw]
        # Intentar agregar id si existe alguna columna que pueda servir
        if bajas and primary_key in bajas[0]:
            for baja in bajas:
                baja['id'] = baja.get(primary_key)
    
    # Si no se encontró primary_key, usar 'id' como default
    if not primary_key:
        primary_key = 'id'
    
    return render_template('ver_bajas.html', bajas=bajas, primary_key=primary_key)


@app.route('/eliminar/<int:equipo_id>', methods=['POST'])
@login_required
def eliminar_equipo(equipo_id):
    if session.get('role') != 'admin':
        flash('Permiso denegado: Solo los administradores pueden eliminar equipos.', 'error')
        return redirect(url_for('dashboard'))

    try:
        db = get_db()
        cursor = db.cursor()
        
        equipo = db.execute('SELECT numero_inventario FROM equipos WHERE id = ?', (equipo_id,)).fetchone()
        
        if equipo:
            numero = equipo['numero_inventario']
            # Eliminar también de la tabla bajas si existe
            cursor.execute('DELETE FROM bajas WHERE equipo_id = ?', (equipo_id,))
            # Eliminar de la tabla equipos
            cursor.execute('DELETE FROM equipos WHERE id = ?', (equipo_id,))
            db.commit()
            flash(f'Equipo {numero} eliminado permanentemente del sistema.', 'success')
        else:
            flash('Error: Equipo no encontrado para eliminar.', 'error')

    except Exception as e:
        flash(f'Ocurrió un error al eliminar el equipo: {e}', 'error')
        
    return redirect(url_for('dashboard'))


@app.route('/eliminar_baja/<baja_id>', methods=['POST'])
@login_required
def eliminar_baja(baja_id):
    """Ruta para eliminar un registro de la tabla bajas."""
    if session.get('role') != 'admin':
        flash('Permiso denegado: Solo los administradores pueden eliminar registros.', 'error')
        return redirect(url_for('ver_bajas'))

    try:
        db = get_db()
        cursor = db.cursor()
        
        # Detectar la clave primaria de la tabla bajas
        table_info = db.execute("PRAGMA table_info(bajas)").fetchall()
        primary_key = None
        
        for info in table_info:
            if info[5] == 1:  # pk es el índice 5
                primary_key = info[1]
                break
        
        # Si no encontramos pk, buscar por nombres comunes
        if not primary_key:
            bajas_columns = [info[1] for info in table_info]
            for col_name in ['id', 'ID', 'Id', '_id']:
                if col_name in bajas_columns:
                    primary_key = col_name
                    break
        
        # Si aún no encontramos, usar 'id' como default
        if not primary_key:
            primary_key = 'id'
        
        # Intentar convertir a int si es posible (para IDs numéricos)
        # Si no es posible, usar el valor como string (para IDs antiguos como 'BJA-2025-0001')
        try:
            baja_id_value = int(baja_id)
        except ValueError:
            baja_id_value = baja_id
        
        # Obtener información de la baja antes de eliminarla
        query = f'SELECT numero_inventario FROM bajas WHERE {primary_key} = ?'
        baja = db.execute(query, (baja_id_value,)).fetchone()
        
        if baja:
            numero = baja['numero_inventario']
            # Eliminar de la tabla bajas usando la clave primaria detectada
            delete_query = f'DELETE FROM bajas WHERE {primary_key} = ?'
            cursor.execute(delete_query, (baja_id_value,))
            db.commit()
            flash(f'Registro de baja del equipo {numero} eliminado permanentemente.', 'success')
        else:
            flash('Error: Registro de baja no encontrado para eliminar.', 'error')

    except Exception as e:
        flash(f'Ocurrió un error al eliminar el registro de baja: {e}', 'error')
        
    return redirect(url_for('ver_bajas'))


# --- EJECUCIÓN DEL SERVIDOR ---

if __name__ == '__main__':
    app.run(debug=True)