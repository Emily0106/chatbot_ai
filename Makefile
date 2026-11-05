COMPOSE_DIR=infra/compose
ENV_FILE=env/dev.env
COMPOSE=docker compose --project-directory $(COMPOSE_DIR) --env-file $(ENV_FILE) \
  -f $(COMPOSE_DIR)/docker-compose.yml -f $(COMPOSE_DIR)/docker-compose.dev.yml

up:
	@test -f $(ENV_FILE) || cp env/.env.example $(ENV_FILE)
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) $(FILES) logs -f --tail=200

ps:
	$(COMPOSE) $(FILES) ps

restart:
	$(COMPOSE) $(FILES) restart

reset-demo:
	@echo "Deleting Qdrant collection people_demo..."
	curl -X DELETE http://localhost:6333/collections/people_demo || true
	@echo "\nTruncating Postgres structured_rows (people demo)..."
	$(COMPOSE) $(FILES) exec -T postgres psql -U app -d rag_db \
		-c "DELETE FROM structured_rows WHERE doc_category='people';" || true
	@echo "Done reset."

ingest-demo:
	@echo "Copying script to container..."
	# We need to find the container ID for ingest-api
	cd infra/compose && docker compose cp ../../apps/ingestion/scripts/ingest_people_demo.py ingest-api:/app/src/ingest_people_demo.py
	@echo "Running ingestion..."
	$(COMPOSE) $(FILES) exec -T ingest-api python /app/src/ingest_people_demo.py

verify-demo:
	@echo "Verifying Qdrant payload (scroll 3 points)..."
	curl -s -X POST "http://localhost:6333/collections/people_demo/points/scroll" \
	  -H "Content-Type: application/json" \
	  -d '{"limit":3,"with_payload":true,"with_vector":false}' | jq .
