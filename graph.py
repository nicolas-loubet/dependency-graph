import os
import re
import networkx as nx
from pyvis.network import Network


# ---------------------------------------------------------
# CONFIGURATION — edit these to match your project
# ---------------------------------------------------------

PROJECT_ROOT = "../"

# File extensions to include as graph nodes
EXTENSIONS = ('.php', '.js', '.java', '.html', '.css')

OUTPUT_FILE = "dependency_graph.html"

# The PHP router file. Its endpoints are used to detect API-level connections between front-end files and handlers.
# Set to None to disable this feature.
ROUTER_FILE = "api.php"

# Directories to skip entirely during scanning
EXCLUDED_DIRS = {
    '.git', 'node_modules', '__pycache__',
    'vendor', 'dist', 'build', 'config', 'data',
}

# Individual files to exclude from the graph (the router itself is excluded from nodes by default)
EXCLUDED_FILES = {
    'api.php',
}

# Edge colors by connection type
COLOR_API         = '#ff4444'   # endpoint resolved through the PHP router
COLOR_IMPORT      = '#44aaff'   # explicit import / require / include
COLOR_SAME_PKG    = '#44ff99'   # Java same-package type reference (no import needed)
# Default edge color (filename literal found in file content) is pyvis default white/gray


# COMMENT STRIPPING
def strip_comments(content, ext):
    if ext in ('.php', '.js', '.java', '.css'):
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        # Avoid stripping URLs (http://, ://) and path separators (//)
        content = re.sub(r'(?<![:/])//(?!//).*', '', content)
    if ext == '.php':
        content = re.sub(r'#.*', '', content)
    if ext == '.html':
        content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    return content


# SCANNING
def scan(project_root):
    """
    Returns:
      file_map      dict { rel_path -> abs_path }
      name_to_paths dict { basename -> [rel_path, ...] }
      router_path   str | None
    """
    file_map      = {}
    name_to_paths = {}
    router_path   = None

    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]

        for filename in files:
            abs_path = os.path.join(root, filename)
            rel_path = os.path.normpath(os.path.relpath(abs_path, project_root))

            if filename == ROUTER_FILE:
                router_path = abs_path

            if filename in EXCLUDED_FILES:
                continue

            if filename.endswith(EXTENSIONS):
                file_map[rel_path] = abs_path
                name_to_paths.setdefault(filename, []).append(rel_path)

    return file_map, name_to_paths, router_path


def resolve_name(basename, name_to_paths):
    return name_to_paths.get(basename, [])


def resolve_import_path(import_str, name_to_paths):
    """
    Given a raw import string such as
    '/../../features/dashboard/views/panel_wallet.php'
    extract the basename and look it up in name_to_paths.
    If the basename has no extension, try common ones.
    """
    basename = os.path.basename(import_str)
    results  = set()

    if '.' not in basename:
        for ext in ('.js', '.php', '.html', '.css', '.java'):
            results.update(resolve_name(basename + ext, name_to_paths))
    else:
        results.update(resolve_name(basename, name_to_paths))

    return results


# SPECIAL IMPORT DETECTION
# Handles patterns where the target filename does not appear
# literally in the source file:
#   - JS/HTML:  import ... from '...', require('...')
#   - PHP/HTML: include __DIR__ . '/path/to/file.php'
#   - Java:     import com.pkg.Class, import com.pkg.*

def extract_special_imports(content, ext, name_to_paths):
    targets = set()

    if ext in ('.js', '.html'):
        for m in re.finditer(r"""import\s+.*?from\s+['"]([^'"]+)['"]""", content):
            targets.update(resolve_import_path(m.group(1), name_to_paths))
        for m in re.finditer(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""", content):
            targets.update(resolve_import_path(m.group(1), name_to_paths))

    if ext in ('.php', '.html'):
        # include/require with a plain string literal
        for m in re.finditer(
            r"""(?:require|include)(?:_once)?\s*\(?['"]([^'"]+)['"]\)?""",
            content
        ):
            targets.update(resolve_import_path(m.group(1), name_to_paths))

        # include/require with __DIR__ concatenation:
        # include __DIR__ . '/../../path/to/file.php'
        for m in re.finditer(
            r"""(?:require|include)(?:_once)?\s*\(?\s*__DIR__\s*\.\s*['"]([^'"]+)['"]\s*\)?""",
            content
        ):
            targets.update(resolve_import_path(m.group(1), name_to_paths))

    if ext == '.java':
        for m in re.finditer(r'import\s+([\w.]+)\s*;', content):
            statement = m.group(1)
            if statement.endswith('.*'):
                # Wildcard: match any .java file whose path contains the package subdirectory
                pkg_path = statement[:-2].replace('.', os.sep)
                for basename, rel_paths in name_to_paths.items():
                    if not basename.endswith('.java'):
                        continue
                    for rel_path in rel_paths:
                        if pkg_path in rel_path:
                            targets.add(rel_path)
            else:
                class_name = statement.split('.')[-1]
                targets.update(resolve_name(class_name + '.java', name_to_paths))

    return targets


# JAVA SAME-PACKAGE DETECTION
def build_java_class_index(file_map):
    """
    Returns:
      file_package  dict { rel_path -> 'com.example.pkg' }
      pkg_classes   dict { 'com.example.pkg' -> { 'ClassName': rel_path } }
    """
    file_package = {}
    pkg_classes  = {}
    pkg_pattern  = re.compile(r'^\s*package\s+([\w.]+)\s*;', re.MULTILINE)

    for rel_path, abs_path in file_map.items():
        if not rel_path.endswith('.java'):
            continue
        try:
            with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                header = ''.join(f.readline() for _ in range(30))

            m       = pkg_pattern.search(header)
            package = m.group(1) if m else '__default__'
            cls     = os.path.splitext(os.path.basename(rel_path))[0]

            file_package[rel_path] = package
            pkg_classes.setdefault(package, {})[cls] = rel_path

        except Exception as e:
            print(f"[java index] could not read {abs_path}: {e}")

    return file_package, pkg_classes


def detect_same_package_types(content, rel_path, file_package, pkg_classes):
    """
    Finds capitalized identifiers in the file body that match
    class names from the same package (excluding self-references).
    """
    targets = set()

    package = file_package.get(rel_path)
    if not package:
        return targets

    peers = pkg_classes.get(package, {})
    if not peers:
        return targets

    own_class = os.path.splitext(os.path.basename(rel_path))[0]

    # Strip import/package declarations so they don't produce false matches
    body = re.sub(
        r'^\s*(?:import|package)\s+[\w.]+\s*(?:\.\*)?\s*;',
        '',
        content,
        flags=re.MULTILINE
    )

    for token in set(re.findall(r'\b([A-Z][A-Za-z0-9_]*)\b', body)):
        if token != own_class and token in peers:
            targets.add(peers[token])

    return targets


# PHP ROUTER PARSING
# Adapt the regex in this function if your router uses a different variable name or syntax.

def parse_router(router_path, name_to_paths):
    routes = {}

    try:
        with open(router_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Locate the route array — change '$allowed_routes' to match your router
        block_match = re.search(
            r'\$(?:rutas_permitidas|allowed_routes)\s*=\s*\[(.*?)\];',
            content,
            flags=re.DOTALL
        )
        if not block_match:
            return routes

        block   = block_match.group(1)
        pattern = re.compile(r"'([^']+)'\s*=>\s*'([^']+\.php)'")

        for endpoint, php_path in pattern.findall(block):
            basename = os.path.basename(php_path)
            for rel_path in resolve_name(basename, name_to_paths):
                routes[endpoint] = rel_path

    except Exception as e:
        print(f"Error reading router: {e}")

    return routes


# GRAPH GENERATION
def build_graph():

    file_map, name_to_paths, router_path = scan(PROJECT_ROOT)

    G = nx.DiGraph()
    G.add_nodes_from(file_map.keys())

    print("Building Java class index...")
    file_package, pkg_classes = build_java_class_index(file_map)
    print(f"  packages found: {len(pkg_classes)}")

    routes = {}
    if ROUTER_FILE and router_path:
        print(f"Parsing router: {router_path}")
        routes = parse_router(router_path, name_to_paths)
        print(f"  endpoints found: {len(routes)}")

    print("Analysing files...")

    for rel_path, abs_path in file_map.items():
        ext = os.path.splitext(rel_path)[1]

        try:
            with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = strip_comments(f.read(), ext)

            # Step 1: filename literal appears in file content
            for other_rel in file_map:
                if other_rel == rel_path:
                    continue
                if os.path.basename(other_rel) in content:
                    G.add_edge(rel_path, other_rel)

            # Step 2: endpoint string appears in file content
            for endpoint, target_rel in routes.items():
                if endpoint in content and target_rel != rel_path:
                    G.add_edge(rel_path, target_rel, kind='api')

            # Step 3: import / require / include patterns
            for target_rel in extract_special_imports(content, ext, name_to_paths):
                if target_rel != rel_path and not G.has_edge(rel_path, target_rel):
                    G.add_edge(rel_path, target_rel, kind='import')

            # Step 4: Java same-package type references
            if ext == '.java':
                for target_rel in detect_same_package_types(
                    content, rel_path, file_package, pkg_classes
                ):
                    if target_rel != rel_path and not G.has_edge(rel_path, target_rel):
                        G.add_edge(rel_path, target_rel, kind='same_pkg')

        except Exception as e:
            print(f"Error processing {abs_path}: {e}")

    # Render
    net = Network(directed=True, height="900px", width="100%",
                  bgcolor="#222222", font_color="white")
    net.from_nx(G)

    for edge in net.edges:
        kind = edge.get('kind')
        if kind == 'api':
            edge['color'] = COLOR_API
            edge['width'] = 3
        elif kind == 'import':
            edge['color'] = COLOR_IMPORT
            edge['width'] = 2
        elif kind == 'same_pkg':
            edge['color'] = COLOR_SAME_PKG
            edge['width'] = 2

    net.show(OUTPUT_FILE, notebook=False)
    print(f"\nGraph saved to: {OUTPUT_FILE}")

    # Report isolated nodes
    isolated = sorted(
        n for n in G.nodes()
        if G.in_degree(n) == 0 and G.out_degree(n) == 0
    )
    if isolated:
        print(f"\nIsolated nodes (no connections detected): {len(isolated)}")
        for node in isolated:
            print(f"  {node}")
    else:
        print("All nodes have at least one connection.")


if __name__ == "__main__":
    build_graph()
