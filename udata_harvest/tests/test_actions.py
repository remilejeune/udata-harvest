# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import logging

from flask.signals import Namespace

from udata.models import Dataset, PeriodicTask

from udata.tests import TestCase, DBTestMixin
from udata.tests.factories import DatasetFactory

from .factories import fake, HarvestSourceFactory
from ..models import HarvestSource, HarvestJob, HarvestError
from .. import actions, signals

from udata.ext.harvest import backends

log = logging.getLogger(__name__)

COUNT = 3

ns = Namespace()

mock_initialize = ns.signal('backend:initialize')
mock_process = ns.signal('backend:process')


@backends.register
class FactoryBackend(backends.BaseBackend):
    name = 'factory'

    def initialize(self):
        '''Parse the index pages HTML to find link to dataset descriptors'''
        mock_initialize.send(self)
        for i in range(self.config.get('count', COUNT)):
            self.add_item(i)

    def process(self, item):
        mock_process.send(self, item=item)
        return DatasetFactory.build(title='dataset-{0}'.format(item.remote_id))


class HarvestActionsTest(DBTestMixin, TestCase):
    def test_list_sources(self):
        self.assertEqual(actions.list_sources(), [])

        sources = [HarvestSourceFactory() for _ in range(3)]
        self.assertEqual(actions.list_sources(), sources)

    def test_create_source(self):
        source_url = fake.url()

        with self.assert_emit(signals.harvest_source_created):
            source = actions.create_source('Test source', source_url, 'dummy')

        self.assertEqual(source.name, 'Test source')
        self.assertEqual(source.slug, 'test-source')
        self.assertEqual(source.url, source_url)
        self.assertEqual(source.backend, 'dummy')
        self.assertEqual(source.frequency, 'manual')
        self.assertIsNone(source.owner)
        self.assertIsNone(source.organization)

    def test_get_source_by_slug(self):
        source = HarvestSourceFactory()
        self.assertEqual(actions.get_source(source.slug), source)

    def test_get_source_by_id(self):
        source = HarvestSourceFactory()
        self.assertEqual(actions.get_source(str(source.id)), source)

    def test_get_source_by_objectid(self):
        source = HarvestSourceFactory()
        self.assertEqual(actions.get_source(source.id), source)

    def test_delete_source_by_slug(self):
        source = HarvestSourceFactory()
        with self.assert_emit(signals.harvest_source_deleted):
            actions.delete_source(source.slug)
        self.assertEqual(len(HarvestSource.objects), 0)

    def test_delete_source_by_id(self):
        source = HarvestSourceFactory()
        with self.assert_emit(signals.harvest_source_deleted):
            actions.delete_source(str(source.id))
        self.assertEqual(len(HarvestSource.objects), 0)

    def test_delete_source_by_objectid(self):
        source = HarvestSourceFactory()
        with self.assert_emit(signals.harvest_source_deleted):
            actions.delete_source(source.id)
        self.assertEqual(len(HarvestSource.objects), 0)

    def test_schedule(self):
        source = HarvestSourceFactory()
        with self.assert_emit(signals.harvest_source_scheduled):
            actions.schedule(str(source.id), hour=0)

        source.reload()
        self.assertEqual(len(PeriodicTask.objects), 1)
        periodic_task = PeriodicTask.objects.first()
        self.assertEqual(source.periodic_task, periodic_task)
        self.assertEqual(periodic_task.args, [str(source.id)])
        self.assertEqual(periodic_task.crontab.hour, '0')
        self.assertEqual(periodic_task.crontab.minute, '*')
        self.assertEqual(periodic_task.crontab.day_of_week, '*')
        self.assertEqual(periodic_task.crontab.day_of_month, '*')
        self.assertEqual(periodic_task.crontab.month_of_year, '*')
        self.assertTrue(periodic_task.enabled)
        self.assertEqual(periodic_task.name, 'Harvest {0}'.format(source.name))

    def test_unschedule(self):
        periodic_task = PeriodicTask.objects.create(
            task='harvest',
            name=fake.name(),
            description=fake.sentence(),
            enabled=True,
            crontab=PeriodicTask.Crontab()
        )
        source = HarvestSourceFactory(periodic_task=periodic_task)
        with self.assert_emit(signals.harvest_source_unscheduled):
            actions.unschedule(str(source.id))

        source.reload()
        self.assertEqual(len(PeriodicTask.objects), 0)
        self.assertIsNone(source.periodic_task)


class ExecutionTestMixin(DBTestMixin):
    def test_default(self):
        source = HarvestSourceFactory(backend='factory')
        with self.assert_emit(signals.before_harvest_job, signals.after_harvest_job):
            self.action(source.slug)

        source.reload()
        self.assertEqual(len(HarvestJob.objects(source=source)), 1)

        job = source.get_last_job()
        self.assertEqual(job.status, 'done')
        self.assertEqual(job.errors, [])
        self.assertIsNotNone(job.started)
        self.assertIsNotNone(job.ended)
        self.assertEqual(len(job.items), COUNT)

        for item in job.items:
            self.assertEqual(item.status, 'done')
            self.assertEqual(item.errors, [])
            self.assertIsNotNone(item.started)
            self.assertIsNotNone(item.ended)

        self.assertEqual(len(HarvestJob.objects), 1)
        self.assertEqual(len(Dataset.objects), COUNT)

    def test_error_on_initialize(self):
        def init(self):
            raise ValueError('test')

        source = HarvestSourceFactory(backend='factory')
        with self.assert_emit(signals.before_harvest_job), mock_initialize.connected_to(init):
            self.action(source.slug)

        source.reload()
        self.assertEqual(len(HarvestJob.objects(source=source)), 1)

        job = source.get_last_job()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(len(job.errors), 1)
        error = job.errors[0]
        self.assertIsInstance(error, HarvestError)
        self.assertIsNotNone(job.started)
        self.assertIsNotNone(job.ended)
        self.assertEqual(len(job.items), 0)

        self.assertEqual(len(HarvestJob.objects), 1)
        self.assertEqual(len(Dataset.objects), 0)

    def test_error_on_item(self):
        def process(self, item):
            if item.remote_id == '1':
                raise ValueError('test')

        source = HarvestSourceFactory(backend='factory')
        with self.assert_emit(signals.before_harvest_job, signals.after_harvest_job), \
             mock_process.connected_to(process):
            self.action(source.slug)

        source.reload()
        self.assertEqual(len(HarvestJob.objects(source=source)), 1)

        job = source.get_last_job()
        self.assertEqual(job.status, 'done-errors')
        self.assertIsNotNone(job.started)
        self.assertIsNotNone(job.ended)
        self.assertEqual(len(job.errors), 0)
        self.assertEqual(len(job.items), COUNT)

        items_ok = filter(lambda i: not len(i.errors), job.items)
        self.assertEqual(len(items_ok), COUNT - 1)

        for item in items_ok:
            self.assertIsNotNone(item.started)
            self.assertIsNotNone(item.ended)
            self.assertEqual(item.status, 'done')
            self.assertEqual(item.errors, [])

        item_ko = filter(lambda i: len(i.errors), job.items)[0]
        self.assertIsNotNone(item_ko.started)
        self.assertIsNotNone(item_ko.ended)
        self.assertEqual(item_ko.status, 'failed')
        self.assertEqual(len(item_ko.errors), 1)

        error = item_ko.errors[0]
        self.assertIsInstance(error, HarvestError)

        self.assertEqual(len(HarvestJob.objects), 1)
        self.assertEqual(len(Dataset.objects), COUNT - 1)


class HarvestLaunchTest(ExecutionTestMixin, TestCase):
    def action(self, *args, **kwargs):
        return actions.launch(*args, **kwargs)


class HarvestRunTest(ExecutionTestMixin, TestCase):
    def action(self, *args, **kwargs):
        return actions.run(*args, **kwargs)
