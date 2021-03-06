# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from collections import OrderedDict
from datetime import datetime

from udata.models import db
from udata.i18n import lazy_gettext as _


HARVEST_FREQUENCIES = OrderedDict((
    ('manual', _('Manual')),
    ('monthly', _('Monthly')),
    ('weekly', _('Weekly')),
    ('daily', _('Daily')),
))

HARVEST_JOB_STATUS = OrderedDict((
    ('pending', _('Pending')),
    ('initializing', _('Initializing')),
    ('initialized', _('Initialized')),
    ('processing', _('Processing')),
    ('done', _('Done')),
    ('done-errors', _('Done with errors')),
    ('failed', _('Failed')),
))

HARVEST_ITEM_STATUS = OrderedDict((
    ('pending', _('Pending')),
    ('started', _('Started')),
    ('done', _('Done')),
    ('failed', _('Failed')),
))

DEFAULT_HARVEST_FREQUENCY = 'manual'
DEFAULT_HARVEST_JOB_STATUS = 'pending'
DEFAULT_HARVEST_ITEM_STATUS = 'pending'


class HarvestError(db.EmbeddedDocument):
    '''Store harvesting errors'''
    created_at = db.DateTimeField(default=datetime.now, required=True)
    message = db.StringField()
    details = db.StringField()


class HarvestItem(db.EmbeddedDocument):
    remote_id = db.StringField()
    status = db.StringField(choices=HARVEST_ITEM_STATUS.keys(), default=DEFAULT_HARVEST_ITEM_STATUS, required=True)
    created = db.DateTimeField(default=datetime.now, required=True)
    started = db.DateTimeField()
    ended = db.DateTimeField()
    errors = db.ListField(db.EmbeddedDocumentField(HarvestError))
    args = db.ListField(db.StringField())
    kwargs = db.DictField()


class HarvestSource(db.Document):
    name = db.StringField(max_length=255)
    slug = db.SlugField(max_length=255, required=True, unique=True, populate_from='name', update=True)
    description = db.StringField()
    url = db.StringField()
    backend = db.StringField()
    config = db.DictField()
    periodic_task = db.ReferenceField('PeriodicTask', reverse_delete_rule=db.NULLIFY)
    created_at = db.DateTimeField(default=datetime.now, required=True)
    frequency = db.StringField(choices=HARVEST_FREQUENCIES.keys(), default=DEFAULT_HARVEST_FREQUENCY, required=True)
    active = db.BooleanField(default=True)

    owner = db.ReferenceField('User', reverse_delete_rule=db.NULLIFY)
    organization = db.ReferenceField('Organization', reverse_delete_rule=db.NULLIFY)

    @classmethod
    def get(cls, ident):
        return cls.objects(slug=ident).first() or cls.objects.get(id=ident)

    def get_last_job(self):
        return HarvestJob.objects(source=self).order_by('-created')[0]


class HarvestJob(db.Document):
    '''Keep track of harvestings'''
    created = db.DateTimeField(default=datetime.now, required=True)
    started = db.DateTimeField()
    ended = db.DateTimeField()
    status = db.StringField(choices=HARVEST_JOB_STATUS.keys(), default=DEFAULT_HARVEST_JOB_STATUS, required=True)
    errors = db.ListField(db.EmbeddedDocumentField(HarvestError))
    items = db.ListField(db.EmbeddedDocumentField(HarvestItem))
    source = db.ReferenceField(HarvestSource, reverse_delete_rule=db.NULLIFY)
