# aws_bitbucket_sg
# Atlassian IP Ranges → AWS Security Group Updater

Script interactivo en Python que consulta la API pública de Atlassian para obtener sus rangos de IP, los filtra por producto y los sincroniza como reglas de entrada SSH (TCP/22) en un Security Group de AWS seleccionado por el usuario.

---

## Tabla de contenidos

- [Requisitos previos](#requisitos-previos)
- [Instalación del entorno virtual](#instalación-del-entorno-virtual)
  - [Ubuntu / Debian](#ubuntu--debian)
  - [AlmaLinux 9 / RHEL 9](#almalinux-9--rhel-9)
  - [macOS](#macos)
- [Uso](#uso)
- [Flujo de ejecución](#flujo-de-ejecución)
- [Referencia de funciones](#referencia-de-funciones)
- [Permisos IAM necesarios](#permisos-iam-necesarios)
- [Salida de ejemplo](#salida-de-ejemplo)

---

## Requisitos previos

| Requisito | Versión mínima |
|-----------|---------------|
| Python    | 3.10          |
| boto3     | 1.34.0        |
| botocore  | 1.34.0        |
| Acceso a internet | Para consultar `ip-ranges.atlassian.com` |
| Credenciales AWS | Access Key ID + Secret Access Key con permisos EC2 |

El resto de dependencias (`json`, `sys`, `getpass`, `math`, `urllib`, `datetime`) forman parte de la librería estándar de Python y no requieren instalación adicional.

---

## Instalación del entorno virtual

### Ubuntu / Debian

```bash
# 1. Instalar paquetes del sistema necesarios
sudo apt update
sudo apt install -y python3 python3-pip python3-venv

# 2. Crear el entorno virtual
python3 -m venv .venv

# 3. Activar el entorno
source .venv/bin/activate

# 4. Instalar dependencias
pip install -r requirements.txt

# 5. Verificar
python3 -c "import boto3; print(boto3.__version__)"
```

Para desactivar el entorno cuando termines:
```bash
deactivate
```

---

### AlmaLinux 9 / RHEL 9

```bash
# 1. Instalar paquetes del sistema necesarios
sudo dnf install -y python3 python3-pip

# python3-venv está incluido en python3 en RHEL9/AlmaLinux9,
# pero si falla el siguiente paso instala también:
sudo dnf install -y python3.11 python3.11-pip   # opcional, si quieres Python 3.11

# 2. Crear el entorno virtual
python3 -m venv .venv

# 3. Activar el entorno
source .venv/bin/activate

# 4. Instalar dependencias
pip install --upgrade pip
pip install -r requirements.txt

# 5. Verificar
python3 -c "import boto3; print(boto3.__version__)"
```

> **Nota:** En AlmaLinux 9 el paquete `python3` instala Python 3.9 por defecto. Si necesitas Python 3.11+, activa el módulo adicional:
> ```bash
> sudo dnf install -y python3.11
> python3.11 -m venv .venv
> ```

Para desactivar el entorno cuando termines:
```bash
deactivate
```

---

### macOS

```bash
# Opción A: usando Homebrew (recomendado)

# 1. Instalar Homebrew si no lo tienes
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Instalar Python
brew install python

# 3. Crear el entorno virtual
python3 -m venv .venv

# 4. Activar el entorno
source .venv/bin/activate

# 5. Instalar dependencias
pip install -r requirements.txt

# 6. Verificar
python3 -c "import boto3; print(boto3.__version__)"
```

```bash
# Opción B: usando pyenv (para gestionar múltiples versiones)

brew install pyenv
pyenv install 3.12.3
pyenv local 3.12.3

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Para desactivar el entorno cuando termines:
```bash
deactivate
```

---

## Uso

```bash
# Activar el entorno virtual (si no está activo)
source .venv/bin/activate

# Ejecutar el script
python3 atlassian_ip_ranges.py
```

El script es completamente interactivo, no acepta argumentos por línea de comandos. Todas las selecciones se realizan mediante menús numerados durante la ejecución.

---

## Flujo de ejecución

```
┌─────────────────────────────────────────────┐
│ 1. Solicitar credenciales AWS               │
│    Access Key ID / Secret / Region          │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│ 2. Validar credenciales                     │
│    describe_account_attributes()            │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│ 3. Listar y seleccionar VPC                 │
│    describe_vpcs() → menú tabular           │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│ 4. Listar y seleccionar Security Group      │
│    describe_security_groups(vpc-id)         │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│ 5. Descargar rangos Atlassian               │
│    GET ip-ranges.atlassian.com              │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│ 6. Seleccionar productos Atlassian          │
│    bitbucket / jira / confluence / etc.     │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│ 7. Analizar Security Group                  │
│    ORIG / MISSING / UNKNOWN                 │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│ 8. Confirmación del usuario                 │
│    Apply changes? [yes/NO]                  │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│ 9. Añadir reglas SSH (TCP/22)               │
│    authorize_security_group_ingress()       │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│ 10. Resumen final                           │
│     ORIG | NEW | UNKNOWN                   │
└─────────────────────────────────────────────┘
```

---

## Referencia de funciones

### Bloque: Constantes globales

```python
SSH_PORT = 22
ATLASSIAN_URL = "https://ip-ranges.atlassian.com/"
```

Define el puerto objetivo (SSH/22) y la URL de la API pública de Atlassian que devuelve el JSON con todos sus rangos de IP.

---

### Bloque: AWS Credentials

#### `prompt_aws_credentials() → boto3.Session`

Solicita interactivamente las credenciales AWS al usuario:
- **AWS Access Key ID** — visible en pantalla
- **AWS Secret Access Key** — oculta con `getpass` (no aparece en pantalla)
- **AWS Region** — con valor por defecto `eu-south-2`

Devuelve un objeto `boto3.Session` configurado con las credenciales proporcionadas. La sesión se usa después para crear el cliente EC2.

---

### Bloque: VPC Selection

#### `list_vpcs(ec2) → list[dict]`

Llama a `describe_vpcs()` y extrae para cada VPC:
- `id` — VPC ID (`vpc-xxxxxxxxx`)
- `cidr` — bloque CIDR principal
- `name` — valor del tag `Name` si existe
- `default` — `True` si es la VPC por defecto de la región

Devuelve la lista ordenada alfabéticamente por VPC ID.

#### `select_vpc_interactive(vpcs) → dict`

Renderiza una tabla con columnas fijas (índice, VPC ID, CIDR, nombre) y espera que el usuario introduzca un número. Valida que el número esté en el rango válido antes de devolver el diccionario de la VPC seleccionada.

---

### Bloque: Security Group Selection

#### `list_sgs_for_vpc(ec2, vpc_id) → list[dict]`

Llama a `describe_security_groups()` filtrando por `vpc-id`. Extrae para cada SG:
- `id` — SG ID (`sg-xxxxxxxxx`)
- `name` — `GroupName`
- `desc` — `Description`

Devuelve la lista ordenada por SG ID.

#### `select_sg_interactive(sgs, vpc_id) → dict`

Renderiza una tabla con columnas fijas (índice, SG ID, Nombre — Descripción) y espera la selección del usuario. Cuando el nombre y la descripción son diferentes, los muestra ambos separados por `—` para dar más contexto.

---

### Bloque: Atlassian helpers

#### `fetch_ip_ranges(url) → dict`

Hace una petición HTTP GET a la URL de Atlassian usando `urllib.request` (sin dependencias externas). Devuelve el JSON completo parseado como diccionario Python.

El JSON tiene esta estructura:
```json
{
  "creationDate": "2026-01-20T00:43:59.934507",
  "syncToken": 1768869839,
  "items": [
    {
      "network": "atlassian",
      "cidr": "13.52.5.0/25",
      "region": "us-west-1",
      "product": ["bitbucket", "jira", "confluence"]
    }
  ]
}
```

#### `is_ipv4(cidr) → bool`

Función auxiliar que determina si un CIDR es IPv4. La lógica es simple: los CIDRs IPv6 siempre contienen `:`, los IPv4 nunca.

#### `get_available_products(data) → list[str]`

Itera todos los items del JSON y extrae los nombres de productos únicos. Normaliza el campo `product` tanto si viene como `str` como si viene como `list`. Devuelve la lista ordenada alfabéticamente.

#### `select_products_interactive(products) → list[str]`

Muestra un menú numerado con todos los productos disponibles más la opción `0` para seleccionar todos. Acepta múltiples selecciones separadas por comas o espacios. Deduplica las selecciones manteniendo el orden.

#### `extract_cidrs_for_products(data, selected_products) → list[str]`

Filtra los items del JSON quedándose solo con los que tienen al menos un producto en la lista seleccionada, descarta los CIDRs IPv6 y devuelve los IPv4 únicos ordenados.

---

### Bloque: AWS SG helpers

#### `get_existing_ssh_cidrs(ec2, sg_id) → set[str]`

Consulta las reglas de entrada (`IpPermissions`) del Security Group y extrae los CIDRs IPv4 que ya tienen acceso al puerto 22 (TCP). Considera tanto reglas específicas TCP/22 como reglas `allow-all` (protocolo `-1`).

#### `add_ssh_ingress_rules(ec2, sg_id, cidrs_to_add) → bool`

Llama a `authorize_security_group_ingress()` para añadir una única petición con todas las reglas TCP/22 a la vez (batch). Cada regla incluye una descripción con la fecha de creación en formato `Atlassian IP (added YYYY-MM-DD)`. Devuelve `True` si tuvo éxito, `False` si la llamada API falló.

---

### Bloque: Display helpers

#### `print_analysis(sg_id, vpc_id, existing, missing, unknown)`

Imprime el análisis previo a la confirmación con tres secciones:
- **SSH CIDRs already present** — cuántas reglas SSH ya existen en el SG
- **CIDRs to ADD** — lista de CIDRs de Atlassian que faltan en el SG (marcados con `+`)
- **Unknown CIDRs** — CIDRs que existen en el SG pero no aparecen en el listado de Atlassian (marcados con `?`)

#### `print_final_summary(sg_id, vpc_id, orig, added, atlassian_set)`

Imprime la tabla resumen tras aplicar los cambios. Cada CIDR recibe una etiqueta:

| Etiqueta | Significado |
|----------|-------------|
| `ORIG`    | Existía en el SG antes de ejecutar el script y está en Atlassian |
| `NEW`     | Añadida en esta ejecución |
| `UNKNOWN` | Existía en el SG pero no aparece en el listado de Atlassian (no se elimina, solo se informa) |

---

### Bloque: Main

#### `main()`

Orquesta el flujo completo en 8 pasos secuenciales:

1. Solicita y valida las credenciales AWS
2. Lista las VPCs disponibles y pide selección
3. Lista los Security Groups de la VPC elegida y pide selección
4. Descarga el JSON de rangos de Atlassian
5. Presenta los productos y pide selección
6. Analiza el SG seleccionado comparándolo con los CIDRs de Atlassian
7. Pide confirmación antes de aplicar cambios (si los hay)
8. Aplica las reglas y muestra el resumen final

---

## Permisos IAM necesarios

El usuario o rol AWS utilizado necesita al menos los siguientes permisos:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeAccountAttributes",
        "ec2:DescribeVpcs",
        "ec2:DescribeSecurityGroups",
        "ec2:AuthorizeSecurityGroupIngress"
      ],
      "Resource": "*"
    }
  ]
}
```

> **Nota de seguridad:** Se recomienda restringir `AuthorizeSecurityGroupIngress` a los recursos específicos en producción usando condiciones ARN.

---

## Salida de ejemplo

```
╔══════════════════════════════════════════════════════════╗
║   Atlassian IP Ranges → AWS Security Group Updater       ║
╚══════════════════════════════════════════════════════════╝

  AWS Access Key ID     : AKIAIOSFODNN7EXAMPLE
  AWS Secret Access Key : ****************
  AWS Region [eu-west-1]: eu-west-1

[+] AWS credentials validated OK

[*] Available VPCs:

  #     VPC ID                    CIDR                Name
  ────────────────────────────────────────────────────────────────────
  [1]   vpc-01583f58e560039cb     10.0.0.0/16         tc-dev-vpc
  [2]   vpc-06d3301fb9e3437b0     10.0.0.0/16         tc-prod-vpc
  [3]   vpc-0f38663883e277500     172.31.0.0/16       tc-blockchain-vpc (default)

  Select VPC number: 1

[+] Selected VPC: vpc-01583f58e560039cb  (10.0.0.0/16)

[*] Security Groups in VPC vpc-01583f58e560039cb:

  #     SG ID                     Name / Description
  ────────────────────────────────────────────────────────────────────────────────
  [1]   sg-0305ae1573536927e      allow_ssh_bitbucket  —  Allow ssh to bitbucket pipelines
  [2]   sg-03c11e5d7332d2254      allow_ssh_by_vpn  —  Permite el acceso ssh a traves de la VPN

  Select Security Group number: 1

[+] Selected SG : sg-0305ae1573536927e  — Allow ssh to bitbucket pipelines

[*] Fetching IP ranges from https://ip-ranges.atlassian.com/ ...

[*] Available products:
    0    ALL (all products)
    1    bitbucket
    2    confluence
    3    forge
    ...

>>> 1

[*] Selected products: bitbucket
[*] Skipped 41 IPv6 CIDRs
[*] Total Atlassian IPv4 CIDRs: 54

═════════════════════════════════════════════════════════════════
  ANALYSIS — Security Groups
═════════════════════════════════════════════════════════════════
  SG  : sg-0305ae1573536927e  (VPC: vpc-01583f58e560039cb)
  SSH CIDRs already present : 31
  CIDRs to ADD              : 23
  CIDRs not in Atlassian    : 3  (UNKNOWN)

  Missing CIDRs (will be added):
    + 104.192.137.0/24
    + 13.52.5.0/25
    + 185.166.142.0/24
    ...

  Unknown CIDRs (already in SG but NOT in Atlassian list):
    ? 0.0.0.0/0
    ? 10.0.0.0/8

═════════════════════════════════════════════════════════════════
  Apply changes? [yes/NO]: yes

[*] Adding 23 rule(s) to sg-0305ae1573536927e ...
[✓] Rules added successfully.


  FINAL SUMMARY
═════════════════════════════════════════════════════════════════
  Security Group : sg-0305ae1573536927e
  VPC            : vpc-01583f58e560039cb
  ─────────────────────────────────────────────────────────────
  CIDR                        STATUS
  ─────────────────────────────────────────────────────────────
  0.0.0.0/0                   UNKNOWN
  10.0.0.0/8                  UNKNOWN
  104.192.137.0/24            NEW
  13.52.5.0/25                ORIG
  185.166.142.0/24            NEW
  ─────────────────────────────────────────────────────────────
  ORIG: 31  |  NEW: 23  |  UNKNOWN: 3
═════════════════════════════════════════════════════════════════
```
