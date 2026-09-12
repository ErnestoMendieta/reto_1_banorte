"""Cliente interactivo de línea de comandos para el endpoint /v1/responses.

Cada ejecución arranca una conversación nueva (no reutiliza conversation_id
de corridas anteriores). Dentro de la misma ejecución, todos los mensajes
comparten el mismo conversation_id para mantener el contexto.

Uso:
    python scripts/chat_cli.py
    python scripts/chat_cli.py --url http://localhost:8080/v1/responses

Escribe "salir" (o "exit"/"quit") para terminar.
"""

import argparse
import sys

import requests

_EXIT_WORDS = {"salir", "exit", "quit"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="http://localhost:8080/v1/responses",
        help="URL del endpoint /v1/responses (default: %(default)s)",
    )
    args = parser.parse_args()

    conversation_id: str | None = None
    print("Nueva conversación. Escribe 'salir' para terminar.\n")

    while True:
        try:
            user_input = input("Tú: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in _EXIT_WORDS:
            break

        payload: dict = {"input": user_input}
        if conversation_id:
            payload["conversation_id"] = conversation_id

        try:
            resp = requests.post(args.url, json=payload, timeout=60)
        except requests.RequestException as exc:
            print(f"[error de conexión] {exc}", file=sys.stderr)
            continue

        if resp.status_code != 200:
            print(f"[error {resp.status_code}] {resp.text}", file=sys.stderr)
            continue

        data = resp.json()
        conversation_id = data.get("conversation_id", conversation_id)

        try:
            text = data["output"][0]["content"][0]["text"]
        except (KeyError, IndexError):
            text = str(data)

        print(f"Agente: {text}\n")


if __name__ == "__main__":
    main()
