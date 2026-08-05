#!/usr/bin/env python3
# -*- coding: utf-8 -*-


class RACError(Exception):
    pass


class DuplicateRecordError(RACError):
    pass


class ValidationError(RACError):
    pass
