# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import logging

from udata.models import User, Organization, PeriodicTask

from . import backends, signals
from .models import HarvestSource, DEFAULT_HARVEST_FREQUENCY
from .tasks import harvest

log = logging.getLogger(__name__)


def list_backends():
    '''List all available backends'''
    return backends.get_all().keys()


def list_sources():
    '''List all harvest sources'''
    return list(HarvestSource.objects)


def get_source(ident):
    '''Get an harvest source given its ID or its slug'''
    return HarvestSource.get(ident)


def create_source(name, url, backend, frequency=DEFAULT_HARVEST_FREQUENCY, owner=None, org=None):
    '''Create a new harvest source'''
    if owner and not isinstance(owner, User):
        owner = User.get(owner)

    if org and not isinstance(org, Organization):
        org = Organization.get(org)

    source = HarvestSource.objects.create(
        name=name,
        url=url,
        backend=backend,
        frequency=frequency or DEFAULT_HARVEST_FREQUENCY,
        owner=owner,
        organization=org
    )
    signals.harvest_source_created.send(source)
    return source


def delete_source(ident):
    '''Delete an harvest source'''
    source = get_source(ident)
    source.delete()
    signals.harvest_source_deleted.send(source)
    # return source


def run(ident, debug=False):
    '''Launch or resume an harvesting for a given source if none is running'''
    source = get_source(ident)
    cls = backends.get(source.backend)
    backend = cls(source, debug=debug)
    backend.harvest()


def launch(ident, debug=False):
    '''Launch or resume an harvesting for a given source if none is running'''
    return harvest.delay(ident)


def schedule(ident, minute='*', hour='*', day_of_week='*', day_of_month='*', month_of_year='*'):
    '''Schedule an harvesting on a source given a crontab'''
    source = get_source(ident)
    if source.periodic_task:
        raise ValueError('Source {0} is already scheduled'.format(source.name))

    source.periodic_task = PeriodicTask.objects.create(
        task='harvest',
        name='Harvest {0}'.format(source.name),
        description='Periodic Harvesting',
        enabled=True,
        args=[str(source.id)],
        crontab=PeriodicTask.Crontab(
            minute=str(minute),
            hour=str(hour),
            day_of_week=str(day_of_week),
            day_of_month=str(day_of_month),
            month_of_year=str(month_of_year)
        ),
    )
    source.save()
    signals.harvest_source_scheduled.send(source)
    return source


def unschedule(ident):
    '''Unschedule an harvesting on a source'''
    source = get_source(ident)
    if not source.periodic_task:
        raise ValueError('Harvesting on source {0} is ot scheduled'.format(source.name))

    source.periodic_task.delete()
    signals.harvest_source_unscheduled.send(source)
    return source
