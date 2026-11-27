# SanA1

After each change, use the four-criterion review in [the jury audit](docs/jury-readiness-audit.md#әр-өзгерістен-кейінгі-бағалау). Record observed outcomes at the tested Git revision, with passing checks, reproduced defects, and the highest-impact remaining issue. Keep simulated responses, live model runs and manual evaluations distinct. Use the same inputs when comparing results. Report measured counts such as labeled cases found, missed, and falsely flagged.

Run the affected regression and the existing Python and JavaScript checks. For audit changes, run the official case, its corrected variants, and the applicable independent fixture pair. For user-flow changes, test the affected path in the browser at 390 and 1440 px. Record tests still pending as unverified.
