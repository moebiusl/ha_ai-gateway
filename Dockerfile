FROM python:3.12-slim

WORKDIR /app

# Postgres + Grafana laufen im selben Container wie das Gateway (bewusste
# Entscheidung: ein einziges Add-on zum Installieren statt drei getrennter).
# Beide ueber die jeweiligen offiziellen Debian/Grafana-APT-Repos, damit
# amd64/aarch64 automatisch von apt aufgeloest werden statt manuell per
# Architektur unterschiedliche Binaries laden zu muessen.
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl gnupg ca-certificates postgresql \
    && curl -fsSL https://apt.grafana.com/gpg.key | gpg --dearmor -o /usr/share/keyrings/grafana.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/grafana.gpg] https://apt.grafana.com stable main" > /etc/apt/sources.list.d/grafana.list \
    && apt-get update && apt-get install -y --no-install-recommends grafana \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "litellm[proxy]" "fastapi==0.115.6" requests pyyaml httpx psycopg2-binary

COPY run.sh status_push.py build_litellm_config.py router.py providers.py custom_callback.py ./
COPY grafana/provisioning /etc/grafana/provisioning
RUN chmod a+x run.sh

CMD [ "./run.sh" ]
