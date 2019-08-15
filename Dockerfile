FROM openmicroscopy/omero-server:5.5
USER root
# Too old: RUN yum install -y python-tox
RUN pip install tox
USER omero-server
RUN echo omero.host=omero > /tmp/ice.config
RUN echo omero.port=4064 >> /tmp/ice.config
RUN echo omero.user=root >> /tmp/ice.config
RUN echo omero.pass=omero >> /tmp/ice.config
RUN echo omero.rootpass=omero >> /tmp/ice.config
ENV ICE_CONFIG /tmp/ice.config
COPY --chown=omero-server:omero-server . /tests
WORKDIR /tests
ENTRYPOINT ["tox"]
