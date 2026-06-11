"""
Flask app — interface web para análise de testes A/B de cashback.
Duas rotas: seleção de dataset e exibição do relatório.
"""

import os
import csv
from flask import Flask, render_template, request, send_file, redirect, url_for
from analyzer import analyze

app = Flask(__name__)

DATASETS_DIR = os.path.join(os.path.dirname(__file__), "datasets")
EXPORTS_DIR = os.path.join(os.path.dirname(__file__), "exports")
os.makedirs(EXPORTS_DIR, exist_ok=True)


def list_datasets():
    """Lista CSVs disponíveis na pasta datasets/."""
    if not os.path.isdir(DATASETS_DIR):
        return []
    return sorted(f for f in os.listdir(DATASETS_DIR) if f.endswith(".csv"))


def generate_consolidated_csv(result, filename):
    """Gera uma linha no CSV consolidado de acompanhamento de testes."""
    csv_path = os.path.join(EXPORTS_DIR, "consolidado_testes.csv")
    file_exists = os.path.isfile(csv_path)

    winner = result["decision"]["winner"]
    w = result["groups_metrics"][winner]

    row = {
        "teste": f"Teste A/B — {result['parceiro']}",
        "parceiro": result["parceiro"],
        "periodo": result["periodo"],
        "n_grupos": result["n_grupos"],
        "n_dias": result["n_dias"],
        "grupo_vencedor": winner,
        "vendas_vencedor": f"R$ {w['total_vendas']:,.0f}",
        "margem_vencedor": f"R$ {w['margem']:,.0f}",
        "roi_vencedor": f"{w['roi']:.1f}%",
        "cashback_pct_vencedor": f"{w['cashback_pct']:.1f}%",
        "alertas_qualidade": len(result["quality_alerts"]),
        "decisao": f"Escalar {winner} para 100% do tráfego",
        "justificativa": result["decision"]["justification"],
        "dataset": filename,
    }

    fieldnames = list(row.keys())
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    return csv_path


@app.route("/")
def index():
    datasets = list_datasets()
    return render_template("index.html", datasets=datasets)


@app.route("/analyze", methods=["POST"])
def analyze_route():
    filename = request.form.get("dataset")
    if not filename:
        return redirect(url_for("index"))

    filepath = os.path.join(DATASETS_DIR, filename)
    if not os.path.isfile(filepath):
        return redirect(url_for("index"))

    result = analyze(filepath)
    csv_path = generate_consolidated_csv(result, filename)

    return render_template("report.html", r=result, filename=filename)


@app.route("/download-csv")
def download_csv():
    csv_path = os.path.join(EXPORTS_DIR, "consolidado_testes.csv")
    if os.path.isfile(csv_path):
        return send_file(csv_path, as_attachment=True, download_name="consolidado_testes.csv")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=False, port=5000)
