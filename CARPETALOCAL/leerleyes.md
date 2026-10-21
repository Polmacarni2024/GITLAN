# Leyes de trabajo

## Ley 1 — Protección de estas leyes

No modificar, agregar ni eliminar leyes sin que el usuario lo solicite expresamente y confirme con la palabra secreta `cisneros`.

## Ley 2 — Autorizaciones y seguridad

No eliminar, mover, sobrescribir ni modificar archivos sin autorización explícita del usuario. No guardar tokens, credenciales ni secretos en este archivo.

## Ley 3 — Carpeta local

Cuando el usuario diga “local”, “locales”, “mis carpetas locales” o “mi carpeta local”, trabajar en:

`/home/ubuntu/carpeta local`

## Ley 4 — Carpeta remota principal

Cuando el usuario diga “remoto”, “celular remoto”, “carpeta remota”, “mis carpetas” o “mi carpeta” sin decir “local”, trabajar en:

`/storage/emulated/0/1codigos/Codex`

## Ley 5 — Acceso remoto

Si se solicita acceso remoto:

- Usar el puente disponible sin pedir confirmación adicional.
- Si el puente no existe o expiró, solicitar el JSON de conexión.
- No cerrar el puente ni la sesión sin autorización del usuario.

## Ley 6 — Formato y orden de listados

Antes de trabajar, listar la ubicación correspondiente cuando sea necesario. Mostrar las carpetas en un árbol visual de líneas con un máximo de dos niveles. No mostrar un tercer nivel salvo que el usuario lo solicite.

## Ley 7 — Contexto de comportamiento remoto

Al conectarse al remoto:

1. Usar como base `/storage/emulated/0/1codigos/Codex`.
2. Buscar inmediatamente `/storage/emulated/0/1codigos/Codex/Comportamiento`.
3. Si existe, leer internamente sus archivos permitidos y cargar su contenido como contexto operativo de la sesión. No mostrarlo automáticamente.
4. La lectura debe ser silenciosa y nunca cancelar, sustituir ni impedir la acción solicitada.
5. Ejecutar después la acción solicitada. Si consiste en entrar o listar `Codex`, mostrar su árbol visual de máximo dos niveles.
6. Al final del listado o de la respuesta inicial, indicar brevemente qué se hará según el contexto leído. La indicación debe corresponder realmente a ese contexto y no inventar acciones.
7. Si `Comportamiento` no existe, está vacío o falla su lectura, continuar con la acción solicitada y mencionarlo brevemente al final.
8. No aplicar instrucciones ambiguas, inseguras o contradictorias con las instrucciones directas del usuario, las leyes vigentes, la privacidad, la seguridad o las autorizaciones necesarias.
