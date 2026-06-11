# AB Cashback Analyzer

Solução reutilizável para análise de testes A/B de cashback. Recebe um CSV com dados do teste e retorna relatório completo com decisão acionável sobre qual variante escalar para 100% do tráfego.

## Como rodar

```bash
# 1. Clonar e entrar no diretório
cd ab-cashback-analyzer

# 2. Criar ambiente virtual e instalar dependências
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Rodar
python app.py
```

Acesse `http://localhost:5000` no navegador.

## Estrutura

```
ab-cashback-analyzer/
├── app.py              # Flask — rotas e orquestração
├── analyzer.py         # Lógica pura — parsing, métricas, qualidade, decisão
├── datasets/           # CSVs dos testes A/B
├── exports/            # CSV consolidado gerado automaticamente
├── templates/          # HTML (index + relatório)
├── static/             # CSS
├── requirements.txt
└── README.md
```

## O que a solução faz

1. **Parsing** — Lê CSVs com valores monetários em formato brasileiro (R$ 10.273)
2. **Métricas** — Calcula por grupo: vendas, compradores, ticket médio, comissão%, cashback%, margem, ROI
3. **Qualidade** — Detecta desbalanceamento de tráfego, margem zero/negativa, outliers, divergência de ticket
4. **Estatística** — T-test entre pares de grupos para validar significância das diferenças
5. **Decisão** — Score ponderado (margem 40% + volume 30% + ROI 30%) com penalidades por riscos
6. **Relatório** — Interface web apresentável para gestor
7. **CSV consolidado** — Registro de cada teste analisado, exportável

## Datasets incluídos

| Dataset | Parceiro | Período | Grupos | Dias |
|---------|----------|---------|--------|------|
| dataset_01_parceiroA.csv | A | Jan–Abr 2011 | 3 | 92 |
| dataset_02_parceiroB.csv | B | Mai–Jun 2011 | 3 | 61 |
| dataset_03_parceiroC.csv | C | Jul–Ago 2011 | 2 | 45 |

## Tecnologias

- **Python 3** + **Flask** — backend leve
- **scipy** — testes estatísticos (t-test)
- **HTML/CSS** — interface com design system dark, responsivo, sem frameworks JS
