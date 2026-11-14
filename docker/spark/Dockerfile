# Local Docker Spark for the 20M-row skew benchmark (Module 7, Artifact 5). Spark 3.5 + Delta 3.2 = Fabric Runtime 1.3.
FROM apache/spark:3.5.3-scala2.12-java17-python3-ubuntu
USER root
RUN pip install --no-cache-dir pyspark==3.5.3 delta-spark==3.2.1
ENV PYTHONPATH=/work/src HOME=/tmp MIZAN_SPARK_BIND=0.0.0.0 MIZAN_DRIVER_MEMORY=5g
WORKDIR /work
