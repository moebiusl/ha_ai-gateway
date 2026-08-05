FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir "litellm[proxy]" "fastapi==0.115.6" requests pyyaml

COPY run.sh status_push.py build_litellm_config.py ./
RUN chmod a+x run.sh

CMD [ "./run.sh" ]
