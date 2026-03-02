---
name: telegram
description: Activa/desactiva notificaciones de Telegram para modo "away". Úsalo cuando te vas de la compu.
user_invocable: true
---

# Telegram Away Mode

Activa o desactiva las notificaciones de Telegram. Cuando está activo, recibes
notificaciones al completar tareas y solicitudes de permisos se reenvían a Telegram.

## Uso

El usuario invoca `/telegram` opcionalmente con argumento `on` u `off`.

## Instrucciones

1. Leer el argumento (default: `on` si no se especifica, o toggle si no hay argumento)
2. Ejecutar la acción correspondiente:

### Activar (on)

```bash
touch /tmp/claude-telegram-active
echo "Telegram away mode ACTIVADO"
```

Confirmar al usuario:
- Notificaciones de completado de tarea: activadas
- Reenvío de solicitudes de permisos: activado
- Para desactivar: `/telegram off`

### Desactivar (off)

```bash
rm -f /tmp/claude-telegram-active
echo "Telegram away mode DESACTIVADO"
```

### Estado (status)

```bash
if [ -f /tmp/claude-telegram-active ]; then echo "ACTIVO"; else echo "INACTIVO"; fi
```

## Notas

- El flag se guarda en `/tmp/claude-telegram-active` (se borra al reiniciar la máquina)
- Los hooks `telegram-away.sh` (Stop y PermissionRequest) verifican este flag
- Sin el flag, los hooks salen en <1ms sin ejecutar nada
