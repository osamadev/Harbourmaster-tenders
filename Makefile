.PHONY: help install run run-cloud smoke smoke-copilot config-check demo dashboard ui redteam index-elastic clean

help:
	@echo "Harbourmaster — make targets"
	@echo "  make install    Install Python deps + the harbourmaster package"
	@echo "  make run        Start ui + phoenix + elastic via docker compose (.env.docker)"
	@echo "  make run-cloud  Start Harbourmaster UI only (use PHOENIX_BASE_URL for cloud)"
	@echo "  make smoke      Verify Gemini + guard + graph flow"
	@echo "  make smoke-copilot  Verify copilot health + native tool path"
	@echo "  make config-check   Print resolved settings and validation results"
	@echo "  make demo       Run the tender-review graph end to end"
	@echo "  make demo SAMPLE=data/sample_tender_human_review.md"
	@echo "  make ui         Launch the Streamlit reviewer UI locally"
	@echo "  make redteam    Run the red-team adversarial scorecard"
	@echo "  make index-elastic  Seed Elastic with policies, samples, and red-team cases"
	@echo "  make dashboard  Print Phoenix and Streamlit dashboard URLs"
	@echo "  make clean      Remove caches and the local audit log"

install:
	pip install -r requirements.txt
	pip install -e .

run:
	docker compose --env-file .env.docker up --build

run-cloud:
	docker compose --env-file .env.cloud up --build ui

smoke:
	python scripts/smoke_test.py

smoke-copilot:
	python scripts/smoke_copilot.py

config-check:
	python scripts/config_check.py

demo:
	python scripts/run_review.py $(SAMPLE)

ui:
	streamlit run app/Home.py

redteam:
	python scripts/run_redteam.py

index-elastic:
	docker compose --env-file .env.docker exec ui python scripts/index_elastic.py

dashboard:
	@python -c "from harbourmaster import config; print(f'Phoenix console: {config.PHOENIX_CONSOLE_URL}/projects/{config.PHOENIX_PROJECT_NAME}'); print('UI:              http://localhost:8501')"

clean:
	python -c "import pathlib, shutil; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
