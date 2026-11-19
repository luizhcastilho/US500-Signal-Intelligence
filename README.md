
# US 500 Signal Intelligence — MVP 1.0

Painel experimental de análise técnica para US 500. Não executa operações e não se conecta à IQ Option.

## O que está incluído
- Importação de candles CSV (preferencialmente M1).
- Formação de candles M5, M15 e H1.
- EMA 9/21/50/200, RSI, MACD, ADX e ATR.
- Regras experimentais de CALL/PUT e filtro de mercado.
- Pontuação técnica e justificativa do sinal.
- Backtest simplificado com entrada no próximo candle M15 e expiração de 15 minutos.
- Exportação do histórico de sinais.

## Instalação
Requer Python 3.10 ou superior.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

O painel abre no navegador. Para acessar no celular, computador e celular precisam estar na mesma rede e o Streamlit deve ser iniciado com `streamlit run app.py --server.address 0.0.0.0`; use apenas em rede confiável e não exponha o serviço diretamente à internet.

## Formato do CSV
Colunas obrigatórias:
- timestamp
- open
- high
- low
- close

Opcional:
- volume

Exemplo:
```csv
timestamp,open,high,low,close,volume
2026-01-05T14:30:00Z,6900.0,6902.0,6898.0,6901.0,120
2026-01-05T14:31:00Z,6901.0,6904.0,6900.0,6903.0,135
```

Os timestamps são interpretados como UTC. Converta corretamente o fuso da fonte antes de importar. O arquivo deve conter candles M1 consecutivos sempre que possível.

## Limitações e cautelas
1. Não há integração ao vivo com IQ Option nesta versão.
2. Não use uma série de preços de outro instrumento como substituta do preço de liquidação da opção. Confirme que símbolo, sessão, timezone e fonte correspondem ao ativo negociado.
3. O backtest é simplificado e não reproduz integralmente regras de liquidação, latência, payout variável ou indisponibilidade de expiração.
4. Pontuação não é probabilidade. Parâmetros precisam ser testados e calibrados fora da amostra.
5. Use primeiro dados históricos, depois acompanhamento em tempo real sem operação e, se apropriado, conta de demonstração.
6. Não há martingale nem execução automática.

## Próxima evolução
Implementar um adaptador de dados autorizado e documentado, após validar o identificador exato do instrumento US 500 na IQ Option e a disponibilidade de dados compatíveis.
