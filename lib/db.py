import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from contextlib import contextmanager
from sqlalchemy.ext.declarative import declarative_base


base = declarative_base()
session = None


def initialize(engine_spec):
    global session
    engine = create_engine(
        engine_spec
    )
    base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = scoped_session(session_factory)


@contextmanager
def sql_ses():
    global session
    logger = logging.getLogger('sql-sm')
    try:
        yield session()
    except BaseException as be:
        logger.error('exception during sql-session (%s), rolling back uncommitted data', be)
        logger.exception(be)
    session.remove()
