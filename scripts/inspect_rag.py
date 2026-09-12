"""
Uso:
    python scripts/inspect_rag.py "¿Cuál es la experiencia laboral de Ernesto?"
    python scripts/inspect_rag.py "stack de IA" --top-k 6
"""

import argparse

from scripts.query_cv import query_cv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="Pregunta a buscar en el CV")
    parser.add_argument("--top-k", type=int, default=4, help="Número de chunks a traer (default: 4)")
    args = parser.parse_args()

    results = query_cv(args.question, top_k=args.top_k)

    if not results:
        print("(sin resultados — ningún chunk superó CV_SIMILARITY_THRESHOLD)")
        return

    for i, chunk in enumerate(results, start=1):
        print(f"--- chunk {i} | similarity={chunk['similarity']:.4f} ---")
        print(f"section: {chunk['section']}")
        print(f"entry_title: {chunk['entry_title']}")
        print("content:")
        print(chunk["content"])
        print()


if __name__ == "__main__":
    main()
