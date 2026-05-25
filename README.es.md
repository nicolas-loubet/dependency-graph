# dependency-graph

Herramienta de análisis estático que escanea un proyecto web y genera un grafo HTML interactivo mostrando cómo se referencian los archivos entre sí.

Diseñada para proyectos que combinan PHP, JavaScript, Java, HTML y CSS, con soporte nativo para routers PHP donde los endpoints están definidos en un archivo central y son invocados por nombre desde el front end.


## Qué detecta

| Tipo de conexión | Color | Descripción |
|---|---|---|
| Nombre de archivo literal | blanco / gris | El basename de un archivo aparece en el contenido de otro |
| Import / include | azul | `import ... from`, `require()`, `include`, `require_once`, `include __DIR__ . '...'` |
| Endpoint API | rojo | Un string de endpoint definido en el router PHP aparece en un archivo |
| Mismo paquete Java | verde | Una clase es referenciada por tipo (campo, parámetro, retorno) sin import explícito, porque ambos archivos están en el mismo paquete |

Todos los bloques de comentarios se eliminan antes del análisis para que las referencias comentadas no generen conexiones falsas.


## Requisitos

```
pip install networkx pyvis
```


## Uso

```bash
python3 graph.py
```

El resultado es un único archivo HTML (`dependency_graph.html` por defecto) que podés abrir en cualquier navegador. El grafo es interactivo: los nodos se pueden arrastrar, hacer zoom y seleccionar.


## Configuración

Todos los ajustes están al principio de `graph.py`. Solo hace falta tocar esta sección.

```python
# Ruta a la raíz del proyecto a analizar.
# Puede ser relativa a la ubicación de graph.py.
PROJECT_ROOT = "../"

# Extensiones a incluir como nodos en el grafo.
EXTENSIONS = ('.php', '.js', '.java', '.html', '.css')

# Nombre del archivo de salida.
OUTPUT_FILE = "dependency_graph.html"

# El router PHP. Poner None si el proyecto no tiene router central.
ROUTER_FILE = "api.php"

# Directorios a omitir por completo.
EXCLUDED_DIRS = {
    '.git', 'node_modules', '__pycache__',
    'vendor', 'dist', 'build', 'config', 'data',
}

# Archivos individuales a excluir del grafo.
EXCLUDED_FILES = {
    'api.php',
}
```


## Soporte para router PHP

Esta herramienta fue construida para un proyecto donde todas las llamadas a la API pasan por un único archivo router PHP que mapea strings de endpoint a archivos handler:

```php
$rutas_permitidas = [
    'dashboard/get' => '/features/dashboard/api/get_dashboard.php',
    'billetera/depositar' => '/features/billetera/api/post_depositar.php',
    ...
];
```

Cuando el analizador encuentra un string como `'dashboard/get'` en un archivo del front end, dibuja una arista roja hacia `get_dashboard.php`, aunque ese nombre de archivo no aparezca literalmente en el front end.

**Para adaptar esto a tu router:**

1. Abrí `graph.py` y buscá la función `parse_router`.
2. Cambiá el regex para que coincida con el nombre de variable o la sintaxis de tu router:

```python
block_match = re.search(
    r'\$(?:rutas_permitidas|allowed_routes)\s*=\s*\[(.*?)\];',
    ...
)
```

3. Si tu router usa un formato completamente distinto (un JSON, un `switch`, el sistema de rutas de un framework), vas a necesitar reescribir `parse_router` para que extraiga pares `(string_endpoint, archivo_handler)`.

Si no tenés un router central, poné `ROUTER_FILE = None` y la funcionalidad se desactiva por completo.


## Adaptar para otros lenguajes

La lógica de detección está dividida en pasos claramente separados dentro de `build_graph`. Para agregar soporte a un nuevo lenguaje o patrón de import:

- **Nueva extensión:** agregala a `EXTENSIONS`.
- **Nueva sintaxis de import:** agregá una rama regex dentro de `extract_special_imports`. La función recibe el contenido limpio del archivo, su extensión y el índice de nombres a rutas.
- **Nuevo tipo de conexión:** agregá un nuevo valor de `kind`, creá la arista con `G.add_edge(..., kind='tu_tipo')` y agregá un color en la sección de estilos dentro de `build_graph`.


## Nodos aislados

Al terminar, el script imprime la lista de archivos sin ninguna conexión detectada. Vale la pena revisarlos manualmente. Las causas más comunes son:

- El archivo solo es referenciado mediante un patrón que el analizador todavía no reconoce.
- El archivo genuinamente no se usa.
- El archivo es referenciado mediante una ruta construida dinámicamente (por ejemplo `include $dir . $nombre . '.php'`), que el análisis estático no puede resolver.


## Estructura del proyecto

```
graph.py        el analizador
README.md       documentación en inglés
README.es.md    este archivo
```


## Licencia

MIT
