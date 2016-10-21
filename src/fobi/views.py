"""
Views.
"""
import datetime
import logging

import simplejson as json

from collections import OrderedDict

from django.db import models, IntegrityError
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.storage import FileSystemStorage
from django.core.urlresolvers import reverse
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import redirect
from django.template import RequestContext
from django.utils.datastructures import MultiValueDictKeyError
from django.utils.translation import ugettext, ugettext_lazy as _

from nine import versions

from .base import (
    fire_form_callbacks,
    run_form_handlers,
    run_form_wizard_handlers,
    form_element_plugin_registry,
    form_handler_plugin_registry,
    form_wizard_handler_plugin_registry,
    submit_plugin_form_data,
    get_theme,
    # get_registered_form_handler_plugins
)
from .constants import (
    CALLBACK_BEFORE_FORM_VALIDATION,
    CALLBACK_FORM_VALID_BEFORE_SUBMIT_PLUGIN_FORM_DATA,
    CALLBACK_FORM_VALID,
    CALLBACK_FORM_VALID_AFTER_FORM_HANDLERS,
    CALLBACK_FORM_INVALID
)
from .decorators import permissions_required, SATISFY_ALL, SATISFY_ANY
from .dynamic import assemble_form_class, assemble_form_wizard_class
from .form_importers import (
    ensure_autodiscover as ensure_importers_autodiscover,
    form_importer_plugin_registry, get_form_impoter_plugin_urls
)
from .forms import (
    FormEntryForm,
    FormElementEntryFormSet,
    ImportFormEntryForm,
    FormWizardEntryForm,
    FormWizardFormEntry,
    FormWizardFormEntryFormSet,
    FormWizardFormEntryForm
)
from .helpers import JSONDataExporter
from .models import (
    FormEntry,
    FormElementEntry,
    FormHandlerEntry,
    FormWizardHandlerEntry,
    FormWizardEntry,
    FormWizardFormEntry,
    FormWizardHandlerEntry
)
from .settings import GET_PARAM_INITIAL_DATA, DEBUG
from .utils import (
    append_edit_and_delete_links_to_field,
    get_user_form_element_plugins_grouped,
    get_user_form_field_plugin_uids,
    # get_user_form_element_plugins,
    # get_user_form_handler_plugins_grouped,
    get_user_form_handler_plugins,
    get_user_form_wizard_handler_plugins,
    get_user_form_handler_plugin_uids,
    get_user_form_wizard_handler_plugin_uids,
    get_wizard_files_upload_dir
)
from .wizard import DynamicSessionWizardView, DynamicCookieWizardView

if versions.DJANGO_GTE_1_10:
    from django.shortcuts import render
else:
    from django.shortcuts import render_to_response

__title__ = 'fobi.views'
__author__ = 'Artur Barseghyan <artur.barseghyan@gmail.com>'
__copyright__ = '2014-2016 Artur Barseghyan'
__license__ = 'GPL 2.0/LGPL 2.1'
__all__ = (
    'add_form_element_entry',
    'add_form_handler_entry',
    'add_form_wizard_form_entry',
    'add_form_wizard_handler_entry',
    'create_form_entry',
    'create_form_wizard_entry',
    'dashboard',
    'delete_form_element_entry',
    'delete_form_entry',
    'delete_form_handler_entry',
    'delete_form_wizard_entry',
    'delete_form_wizard_form_entry',
    'edit_form_element_entry',
    'edit_form_entry',
    'edit_form_handler_entry',
    'edit_form_wizard_handler_entry',
    'export_form_entry',
    'form_entry_submitted',
    'form_importer',
    'form_wizard_entry_submitted',
    'form_wizards_dashboard',
    'FormWizardView',
    'import_form_entry',
    'view_form_entry',
)

logger = logging.getLogger(__name__)

# *****************************************************************************
# *****************************************************************************
# *********************************** Generic *********************************
# *****************************************************************************
# *****************************************************************************


def _delete_plugin_entry(request,
                         entry_id,
                         EntryModel,
                         get_user_plugin_uids_func,
                         message,
                         html_anchor):
    """Abstract delete entry.

    :param django.http.HttpRequest request:
    :param int entry_id:
    :param fobi.models.AbstractPluginEntry EntryModel: Subclass of
        ``fobi.models.AbstractPluginEntry``.
    :param callable get_user_plugin_uids_func:
    :param str message:
    :return django.http.HttpResponse:
    """
    try:
        obj = EntryModel._default_manager \
                        .select_related('form_entry') \
                        .get(pk=entry_id, form_entry__user__pk=request.user.pk)
    except ObjectDoesNotExist as err:
        raise Http404(_("{0} not found."
                        "").format(EntryModel._meta.verbose_name))

    form_entry = obj.form_entry
    plugin = obj.get_plugin(request=request)
    plugin.request = request

    plugin._delete_plugin_data()

    obj.delete()

    messages.info(request, message.format(plugin.name))

    redirect_url = reverse(
        'fobi.edit_form_entry', kwargs={'form_entry_id': form_entry.pk}
    )
    return redirect("{0}{1}".format(redirect_url, html_anchor))


def _delete_wizard_plugin_entry(request,
                                entry_id,
                                EntryModel,
                                get_user_plugin_uids_func,
                                message,
                                html_anchor):
    """Abstract delete wizard entry.

    :param django.http.HttpRequest request:
    :param int entry_id:
    :param fobi.models.AbstractPluginEntry EntryModel: Subclass of
        ``fobi.models.AbstractPluginEntry``.
    :param str message:
    :return django.http.HttpResponse:
    """
    try:
        obj = EntryModel._default_manager \
                        .select_related('form_wizard_entry') \
                        .get(pk=entry_id,
                             form_wizard_entry__user__pk=request.user.pk)
    except ObjectDoesNotExist as err:
        raise Http404(_("{0} not found."
                        "").format(EntryModel._meta.verbose_name))

    form_wizard_entry_id = obj.form_wizard_entry_id

    plugin = obj.get_plugin(request=request)
    plugin.request = request

    plugin._delete_plugin_data()

    obj.delete()

    messages.info(request, message.format(plugin.name))

    redirect_url = reverse(
        'fobi.edit_form_wizard_entry',
        kwargs={'form_wizard_entry_id': form_wizard_entry_id}
    )
    return redirect("{0}{1}".format(redirect_url, html_anchor))


# *****************************************************************************
# *****************************************************************************
# ******************************** Dashboards *********************************
# *****************************************************************************
# *****************************************************************************

# *****************************************************************************
# ********************************** Forms ************************************
# *****************************************************************************

dashboard_permissions = [
    # Form
    'fobi.add_formentry',
    'fobi.change_formentry',
    'fobi.delete_formentry',
]


@login_required
@permissions_required(satisfy=SATISFY_ANY, perms=dashboard_permissions)
def dashboard(request, theme=None, template_name=None):
    """Dashboard.

    :param django.http.HttpRequest request:
    :param fobi.base.BaseTheme theme: Theme instance.
    :param string template_name:
    :return django.http.HttpResponse:
    """
    form_entries = FormEntry._default_manager \
                            .filter(user__pk=request.user.pk) \
                            .select_related('user')

    context = {
        'form_entries': form_entries,
        'form_importers': get_form_impoter_plugin_urls(),
    }

    # If given, pass to the template (and override the value set by
    # the context processor.
    if theme:
        context.update({'fobi_theme': theme})

    if not template_name:
        theme = get_theme(request=request, as_instance=True)
        template_name = theme.dashboard_template

    if versions.DJANGO_GTE_1_10:
        return render(request, template_name, context)
    else:
        return render_to_response(
            template_name, context, context_instance=RequestContext(request)
        )

# *****************************************************************************
# ****************************** Form wizards *********************************
# *****************************************************************************

wizards_dashboard_permissions = [
    # Form wizard
    'fobi.add_formwizardentry',
    'fobi.change_formwizardentry',
    'fobi.delete_formwizardentry',
]


@login_required
@permissions_required(satisfy=SATISFY_ANY, perms=wizards_dashboard_permissions)
def form_wizards_dashboard(request, theme=None, template_name=None):
    """Dashboard for form wizards.

    :param django.http.HttpRequest request:
    :param fobi.base.BaseTheme theme: Theme instance.
    :param string template_name:
    :return django.http.HttpResponse:
    """
    form_wizard_entries = FormWizardEntry._default_manager \
        .filter(user__pk=request.user.pk) \
        .select_related('user')

    context = {
        'form_wizard_entries': form_wizard_entries,
        # 'form_importers': get_form_impoter_plugin_urls(),
    }

    # If given, pass to the template (and override the value set by
    # the context processor.
    if theme:
        context.update({'fobi_theme': theme})

    if not template_name:
        theme = get_theme(request=request, as_instance=True)
        template_name = theme.form_wizards_dashboard_template

    if versions.DJANGO_GTE_1_10:
        return render(request, template_name, context)
    else:
        return render_to_response(
            template_name, context, context_instance=RequestContext(request)
        )

# *****************************************************************************
# *****************************************************************************
# ********************************** Builder **********************************
# *****************************************************************************
# *****************************************************************************

# *****************************************************************************
# **************************** Create form entry ******************************
# *****************************************************************************

create_form_entry_permissions = [
    'fobi.add_formentry',
    'fobi.add_formelemententry',
    'fobi.add_formhandlerentry',
]


@login_required
@permissions_required(satisfy=SATISFY_ALL, perms=create_form_entry_permissions)
def create_form_entry(request, theme=None, template_name=None):
    """Create form entry.

    :param django.http.HttpRequest request:
    :param fobi.base.BaseTheme theme: Theme instance.
    :param str template_name:
    :return django.http.HttpResponse:
    """
    if 'POST' == request.method:
        form = FormEntryForm(request.POST, request.FILES, request=request)
        if form.is_valid():
            form_entry = form.save(commit=False)
            form_entry.user = request.user
            try:
                form_entry.save()
                messages.info(
                    request,
                    _('Form {0} was created '
                      'successfully.').format(form_entry.name)
                )
                return redirect(
                    'fobi.edit_form_entry', form_entry_id=form_entry.pk
                )
            except IntegrityError as err:
                messages.info(
                    request,
                    _('Errors occurred while saving '
                      'the form: {0}.').format(str(err))
                )

    else:
        form = FormEntryForm(request=request)

    context = {'form': form}

    # If given, pass to the template (and override the value set by
    # the context processor.
    if theme:
        context.update({'fobi_theme': theme})

    if not template_name:
        if not theme:
            theme = get_theme(request=request, as_instance=True)
        template_name = theme.create_form_entry_template

    if versions.DJANGO_GTE_1_10:
        return render(request, template_name, context)
    else:
        return render_to_response(
            template_name, context, context_instance=RequestContext(request)
        )

# **************************************************************************
# ******************************* Edit form entry **************************
# **************************************************************************

edit_form_entry_permissions = [
    'fobi.change_formentry', 'fobi.change_formelemententry',
    'fobi.change_formhandlerentry',
    'fobi.add_formelemententry', 'fobi.add_formhandlerentry',
    'fobi.delete_formelemententry', 'fobi.delete_formhandlerentry',
]


@login_required
@permissions_required(satisfy=SATISFY_ANY, perms=edit_form_entry_permissions)
def edit_form_entry(request, form_entry_id, theme=None, template_name=None):
    """Edit form entry.

    :param django.http.HttpRequest request:
    :param int form_entry_id:
    :param fobi.base.BaseTheme theme: Theme instance.
    :param str template_name:
    :return django.http.HttpResponse:
    """
    try:
        form_entry = FormEntry._default_manager \
                              .select_related('user') \
                              .prefetch_related('formelemententry_set') \
                              .get(pk=form_entry_id, user__pk=request.user.pk)
    # .prefetch_related('formhandlerentry_set') \
    except ObjectDoesNotExist as err:
        raise Http404(ugettext("Form entry not found."))

    if 'POST' == request.method:
        # The form entry form (does not contain form elements)
        form = FormEntryForm(request.POST, request.FILES, instance=form_entry,
                             request=request)

        # This is where we save ordering if it has been changed.
        # The `FormElementEntryFormSet` contain ids and positions only.
        if 'ordering' in request.POST:
            form_element_entry_formset = FormElementEntryFormSet(
                request.POST,
                request.FILES,
                queryset=form_entry.formelemententry_set.all(),
                # prefix = 'form_element'
            )
            # If form elements aren't properly made (developers's fault)
            # there might be problems with saving the ordering - likely
            # in case of hidden elements only. Thus, we want to avoid
            # errors here.
            try:
                if form_element_entry_formset.is_valid():
                    form_element_entry_formset.save()
                    messages.info(
                        request,
                        _("Elements ordering edited successfully.")
                    )
                    return redirect(
                        reverse('fobi.edit_form_entry',
                                kwargs={'form_entry_id': form_entry_id})
                    )
            except MultiValueDictKeyError as err:
                messages.error(
                    request,
                    _("Errors occurred while trying to change the "
                      "elements ordering!")
                )
                return redirect(
                    reverse('fobi.edit_form_entry',
                            kwargs={'form_entry_id': form_entry_id})
                )
        else:
            form_element_entry_formset = FormElementEntryFormSet(
                queryset=form_entry.formelemententry_set.all(),
                # prefix='form_element'
            )

        if form.is_valid():
            obj = form.save(commit=False)
            obj.user = request.user
            try:
                obj.save()
                messages.info(
                    request,
                    _('Form {0} was edited '
                      'successfully.').format(form_entry.name)
                )
                return redirect(
                    reverse('fobi.edit_form_entry',
                            kwargs={'form_entry_id': form_entry_id})
                    )
            except IntegrityError as err:
                messages.info(
                    request,
                    _('Errors occurred while saving '
                      'the form: {0}.').format(str(err))
                )
    else:
        # The form entry form (does not contain form elements)
        form = FormEntryForm(instance=form_entry, request=request)

        form_element_entry_formset = FormElementEntryFormSet(
            queryset=form_entry.formelemententry_set.all(),
            # prefix='form_element'
        )

    # In case of success, we don't need this (since redirect would happen).
    # Thus, fetch only if needed.
    form_elements = form_entry.formelemententry_set.all()
    form_handlers = form_entry.formhandlerentry_set.all()[:]
    used_form_handler_uids = [form_handler.plugin_uid
                              for form_handler
                              in form_handlers]

    # The code below (two lines below) is not really used at the moment,
    # thus - comment out, but do not remove, as we might need it later on.
    # all_form_entries = FormEntry._default_manager \
    #                            .only('id', 'name', 'slug') \
    #                            .filter(user__pk=request.user.pk)

    # List of form element plugins allowed to user
    user_form_element_plugins = get_user_form_element_plugins_grouped(
        request.user
    )
    # List of form handler plugins allowed to user
    user_form_handler_plugins = get_user_form_handler_plugins(
        request.user,
        exclude_used_singles=True,
        used_form_handler_plugin_uids=used_form_handler_uids
    )

    # Assembling the form for preview
    FormClass = assemble_form_class(
        form_entry,
        origin='edit_form_entry',
        origin_kwargs_update_func=append_edit_and_delete_links_to_field,
        request=request
    )

    assembled_form = FormClass()

    # In debug mode, try to identify possible problems.
    if DEBUG:
        assembled_form.as_p()
    else:
        try:
            assembled_form.as_p()
        except Exception as err:
            logger.error(err)

    # If no theme provided, pick a default one.
    if not theme:
        theme = get_theme(request=request, as_instance=True)

    theme.collect_plugin_media(form_elements)

    context = {
        'form': form,
        'form_entry': form_entry,
        'form_elements': form_elements,
        'form_handlers': form_handlers,
        # 'all_form_entries': all_form_entries,
        'user_form_element_plugins': user_form_element_plugins,
        'user_form_handler_plugins': user_form_handler_plugins,
        'assembled_form': assembled_form,
        'form_element_entry_formset': form_element_entry_formset,
        'fobi_theme': theme,
    }

    if not template_name:
        template_name = theme.edit_form_entry_template

    if versions.DJANGO_GTE_1_10:
        return render(request, template_name, context)
    else:
        return render_to_response(
            template_name, context, context_instance=RequestContext(request)
        )

# *****************************************************************************
# ********************************* Delete form entry *************************
# *****************************************************************************

delete_form_entry_permissions = [
    'fobi.delete_formentry', 'fobi.delete_formelemententry',
    'fobi.delete_formhandlerentry',
]


@login_required
@permissions_required(satisfy=SATISFY_ALL,
                      perms=delete_form_entry_permissions)
def delete_form_entry(request, form_entry_id, template_name=None):
    """Delete form entry.

    :param django.http.HttpRequest request:
    :param int form_entry_id:
    :param string template_name:
    :return django.http.HttpResponse:
    """
    try:
        obj = FormEntry._default_manager \
            .get(pk=form_entry_id, user__pk=request.user.pk)
    except ObjectDoesNotExist as err:
        raise Http404(ugettext("Form entry not found."))

    obj.delete()

    messages.info(
        request,
        _('The form "{0}" was deleted successfully.').format(obj.name)
    )

    return redirect('fobi.dashboard')

# *****************************************************************************
# **************************** Add form element entry *************************
# *****************************************************************************


@login_required
@permission_required('fobi.add_formelemententry')
def add_form_element_entry(request,
                           form_entry_id,
                           form_element_plugin_uid,
                           theme=None,
                           template_name=None):
    """Add form element entry.

    :param django.http.HttpRequest request:
    :param int form_entry_id:
    :param int form_element_plugin_uid:
    :param fobi.base.BaseTheme theme: Theme instance.
    :param string template_name:
    :return django.http.HttpResponse:
    """
    try:
        form_entry = FormEntry._default_manager \
                              .prefetch_related('formelemententry_set') \
                              .get(pk=form_entry_id)
    except ObjectDoesNotExist as err:
        raise Http404(ugettext("Form entry not found."))

    form_elements = form_entry.formelemententry_set.all()

    user_form_element_plugin_uids = get_user_form_field_plugin_uids(
        request.user
    )

    if form_element_plugin_uid not in user_form_element_plugin_uids:
        raise Http404(ugettext("Plugin does not exist or you are not allowed "
                               "to use this plugin!"))

    FormElementPlugin = form_element_plugin_registry.get(
        form_element_plugin_uid
    )
    form_element_plugin = FormElementPlugin(user=request.user)
    form_element_plugin.request = request

    FormElementPluginForm = form_element_plugin.get_form()
    form = None

    obj = FormElementEntry()
    obj.form_entry = form_entry
    obj.plugin_uid = form_element_plugin_uid
    obj.user = request.user

    save_object = False

    # If plugin doesn't have a form
    if not FormElementPluginForm:
        save_object = True

    # If POST
    elif 'POST' == request.method:
        # If element has a form
        form = form_element_plugin.get_initialised_create_form_or_404(
            data=request.POST,
            files=request.FILES
            )
        form.validate_plugin_data(form_elements, request=request)
        if form.is_valid():
            # Saving the plugin form data.
            form.save_plugin_data(request=request)

            # Getting the plugin data.
            obj.plugin_data = form.get_plugin_data(request=request)

            save_object = True

    # If not POST
    else:
        form = form_element_plugin.get_initialised_create_form_or_404()

    if save_object:
        # Handling the position
        position = 1
        records = FormElementEntry.objects.filter(form_entry=form_entry) \
                                  .aggregate(models.Max('position'))
        if records:
            try:
                position = records['{0}__max'.format('position')] + 1

            except TypeError as err:
                pass

        obj.position = position

        # Save the object.
        obj.save()

        messages.info(
            request,
            _('The form element plugin "{0}" was added '
              'successfully.').format(form_element_plugin.name)
        )
        return redirect(
            "{0}?active_tab=tab-form-elements".format(
                reverse('fobi.edit_form_entry',
                        kwargs={'form_entry_id': form_entry_id})
            )
        )

    context = {
        'form': form,
        'form_entry': form_entry,
        'form_element_plugin': form_element_plugin,
    }

    # If given, pass to the template (and override the value set by
    # the context processor.
    if theme:
        context.update({'fobi_theme': theme})

    if not template_name:
        if not theme:
            theme = get_theme(request=request, as_instance=True)
        template_name = theme.add_form_element_entry_template

    if versions.DJANGO_GTE_1_10:
        return render(request, template_name, context)
    else:
        return render_to_response(
            template_name, context, context_instance=RequestContext(request)
        )

# *****************************************************************************
# **************************** Edit form element entry ************************
# *****************************************************************************


@login_required
@permission_required('fobi.change_formelemententry')
def edit_form_element_entry(request,
                            form_element_entry_id,
                            theme=None,
                            template_name=None):
    """Edit form element entry.

    :param django.http.HttpRequest request:
    :param int form_element_entry_id:
    :param fobi.base.BaseTheme: Theme instance.
    :param string template_name:
    :return django.http.HttpResponse:
    """
    try:
        obj = FormElementEntry._default_manager \
                              .select_related('form_entry',
                                              'form_entry__user') \
                              .get(pk=form_element_entry_id,
                                   form_entry__user__pk=request.user.pk)
    except ObjectDoesNotExist as err:
        raise Http404(ugettext("Form element entry not found."))

    form_entry = obj.form_entry
    form_element_plugin = obj.get_plugin(request=request)
    form_element_plugin.request = request

    FormElementPluginForm = form_element_plugin.get_form()
    form = None

    if not FormElementPluginForm:
        messages.info(
            request,
            _('The form element plugin "{0}" '
              'is not configurable!').format(form_element_plugin.name)
        )
        return redirect('fobi.edit_form_entry', form_entry_id=form_entry.pk)

    elif 'POST' == request.method:
        form = form_element_plugin.get_initialised_edit_form_or_404(
            data=request.POST,
            files=request.FILES
        )

        form_elements = FormElementEntry._default_manager \
                                        .select_related('form_entry',
                                                        'form_entry__user') \
                                        .exclude(pk=form_element_entry_id) \
                                        .filter(form_entry=form_entry)

        form.validate_plugin_data(form_elements, request=request)

        if form.is_valid():
            # Saving the plugin form data.
            form.save_plugin_data(request=request)

            # Getting the plugin data.
            obj.plugin_data = form.get_plugin_data(request=request)

            # Save the object.
            obj.save()

            messages.info(
                request,
                _('The form element plugin "{0}" was edited '
                  'successfully.').format(form_element_plugin.name)
            )

            return redirect('fobi.edit_form_entry',
                            form_entry_id=form_entry.pk)

    else:
        form = form_element_plugin.get_initialised_edit_form_or_404()

    form_element_plugin = obj.get_plugin(request=request)
    form_element_plugin.request = request

    context = {
        'form': form,
        'form_entry': form_entry,
        'form_element_plugin': form_element_plugin,
    }

    # If given, pass to the template (and override the value set by
    # the context processor.
    if theme:
        context.update({'fobi_theme': theme})

    if not template_name:
        if not theme:
            theme = get_theme(request=request, as_instance=True)
        template_name = theme.edit_form_element_entry_template

    if versions.DJANGO_GTE_1_10:
        return render(request, template_name, context)
    else:
        return render_to_response(
            template_name, context, context_instance=RequestContext(request)
        )

# *****************************************************************************
# **************************** Delete form element entry **********************
# *****************************************************************************


@login_required
@permission_required('fobi.delete_formelemententry')
def delete_form_element_entry(request, form_element_entry_id):
    """Delete form element entry.

    :param django.http.HttpRequest request:
    :param int form_element_entry_id:
    :return django.http.HttpResponse:
    """
    return _delete_plugin_entry(
        request=request,
        entry_id=form_element_entry_id,
        EntryModel=FormElementEntry,
        get_user_plugin_uids_func=get_user_form_field_plugin_uids,
        message=_('The form element plugin "{0}" was deleted successfully.'),
        html_anchor='?active_tab=tab-form-elements'
    )

# *****************************************************************************
# **************************** Add form handler entry *************************
# *****************************************************************************


@login_required
@permission_required('fobi.add_formhandlerentry')
def add_form_handler_entry(request,
                           form_entry_id,
                           form_handler_plugin_uid,
                           theme=None,
                           template_name=None):
    """Add form handler entry.

    :param django.http.HttpRequest request:
    :param int form_entry_id:
    :param int form_handler_plugin_uid:
    :param fobi.base.BaseTheme theme: Theme instance.
    :param string template_name:
    :return django.http.HttpResponse:
    """
    try:
        form_entry = FormEntry._default_manager.get(pk=form_entry_id)
    except ObjectDoesNotExist as err:
        raise Http404(ugettext("Form entry not found."))

    user_form_handler_plugin_uids = get_user_form_handler_plugin_uids(
        request.user
    )

    if form_handler_plugin_uid not in user_form_handler_plugin_uids:
        raise Http404(ugettext("Plugin does not exist or you are not allowed "
                               "to use this plugin!"))

    FormHandlerPlugin = form_handler_plugin_registry.get(
        form_handler_plugin_uid
    )

    # Check if we deal with form handler plugin that is only allowed to be
    # used once. In that case, check if it has been used already in the current
    # form entry.
    if not FormHandlerPlugin.allow_multiple:
        times_used = FormHandlerEntry._default_manager \
            .filter(form_entry__id=form_entry_id,
                    plugin_uid=FormHandlerPlugin.uid) \
            .count()
        if times_used > 0:
            raise Http404(ugettext("The {0} plugin can be used only once in a "
                                   "form.").format(FormHandlerPlugin.name))

    form_handler_plugin = FormHandlerPlugin(user=request.user)
    form_handler_plugin.request = request

    FormHandlerPluginForm = form_handler_plugin.get_form()
    form = None

    obj = FormHandlerEntry()
    obj.form_entry = form_entry
    obj.plugin_uid = form_handler_plugin_uid
    obj.user = request.user

    save_object = False

    if not FormHandlerPluginForm:
        save_object = True

    elif 'POST' == request.method:
        form = form_handler_plugin.get_initialised_create_form_or_404(
            data=request.POST,
            files=request.FILES
        )
        if form.is_valid():
            # Saving the plugin form data.
            form.save_plugin_data(request=request)

            # Getting the plugin data.
            obj.plugin_data = form.get_plugin_data(request=request)

            save_object = True

    else:
        form = form_handler_plugin.get_initialised_create_form_or_404()

    if save_object:
        # Save the object.
        obj.save()

        messages.info(
            request,
            _('The form handler plugin "{0}" was added '
              'successfully.').format(form_handler_plugin.name)
        )
        return redirect(
            "{0}?active_tab=tab-form-handlers".format(
                reverse(
                    'fobi.edit_form_entry',
                    kwargs={'form_entry_id': form_entry_id}
                )
            )
        )

    context = {
        'form': form,
        'form_entry': form_entry,
        'form_handler_plugin': form_handler_plugin,
    }

    # If given, pass to the template (and override the value set by
    # the context processor.
    if theme:
        context.update({'fobi_theme': theme})

    if not template_name:
        if not theme:
            theme = get_theme(request=request, as_instance=True)
        template_name = theme.add_form_handler_entry_template

    if versions.DJANGO_GTE_1_10:
        return render(request, template_name, context)
    else:
        return render_to_response(
            template_name, context, context_instance=RequestContext(request)
        )

# *****************************************************************************
# **************************** Edit form handler entry ************************
# *****************************************************************************


@login_required
@permission_required('fobi.change_formhandlerentry')
def edit_form_handler_entry(request,
                            form_handler_entry_id,
                            theme=None,
                            template_name=None):
    """Edit form handler entry.

    :param django.http.HttpRequest request:
    :param int form_handler_entry_id:
    :param fobi.base.BaseTheme theme: Theme instance.
    :param string template_name:
    :return django.http.HttpResponse:
    """
    try:
        obj = FormHandlerEntry._default_manager \
                              .select_related('form_entry') \
                              .get(pk=form_handler_entry_id)
    except ObjectDoesNotExist as err:
        raise Http404(ugettext("Form handler entry not found."))

    form_entry = obj.form_entry

    form_handler_plugin = obj.get_plugin(request=request)
    form_handler_plugin.request = request

    FormHandlerPluginForm = form_handler_plugin.get_form()
    form = None

    if not FormHandlerPluginForm:
        messages.info(
            request,
            _('The form handler plugin "{0}" is not '
              'configurable!').format(form_handler_plugin.name)
        )
        return redirect('fobi.edit_form_entry', form_entry_id=form_entry.pk)

    elif 'POST' == request.method:
        form = form_handler_plugin.get_initialised_edit_form_or_404(
            data=request.POST,
            files=request.FILES
        )

        if form.is_valid():
            # Saving the plugin form data.
            form.save_plugin_data(request=request)

            # Getting the plugin data.
            obj.plugin_data = form.get_plugin_data(request=request)

            # Save the object.
            obj.save()

            messages.info(
                request,
                _('The form handler plugin "{0}" was edited '
                  'successfully.').format(form_handler_plugin.name)
            )

            return redirect('fobi.edit_form_entry',
                            form_entry_id=form_entry.pk)

    else:
        form = form_handler_plugin.get_initialised_edit_form_or_404()

    context = {
        'form': form,
        'form_entry': form_entry,
        'form_handler_plugin': form_handler_plugin,
    }

    # If given, pass to the template (and override the value set by
    # the context processor.
    if theme:
        context.update({'fobi_theme': theme})

    if not template_name:
        if not theme:
            theme = get_theme(request=request, as_instance=True)
        template_name = theme.edit_form_handler_entry_template

    if versions.DJANGO_GTE_1_10:
        return render(request, template_name, context)
    else:
        return render_to_response(
            template_name, context, context_instance=RequestContext(request)
        )

# *****************************************************************************
# **************************** Delete form handler entry **********************
# *****************************************************************************


@login_required
@permission_required('fobi.delete_formhandlerentry')
def delete_form_handler_entry(request, form_handler_entry_id):
    """Delete form handler entry.

    :param django.http.HttpRequest request:
    :param int form_handler_entry_id:
    :return django.http.HttpResponse:
    """
    return _delete_plugin_entry(
        request=request,
        entry_id=form_handler_entry_id,
        EntryModel=FormHandlerEntry,
        get_user_plugin_uids_func=get_user_form_handler_plugin_uids,
        message=_('The form handler plugin "{0}" was deleted successfully.'),
        html_anchor='?active_tab=tab-form-handlers'
    )

# *****************************************************************************
# *****************************************************************************
# ****************************** Form wizard **********************************
# *****************************************************************************
# *****************************************************************************

# *****************************************************************************
# ************************* Create form wizard entry **************************
# *****************************************************************************

create_form_wizard_entry_permissions = [
    'fobi.add_formwizardentry',
    'fobi.add_formwizardformentry',
    'fobi.add_formhandlerentry',
]


@login_required
@permissions_required(satisfy=SATISFY_ALL,
                      perms=create_form_wizard_entry_permissions)
def create_form_wizard_entry(request, theme=None, template_name=None):
    """Create form wizard entry.

    :param django.http.HttpRequest request:
    :param fobi.base.BaseTheme theme: Theme instance.
    :param str template_name:
    :return django.http.HttpResponse:
    """
    if 'POST' == request.method:
        form = FormWizardEntryForm(request.POST,
                                   request.FILES,
                                   request=request)
        if form.is_valid():
            form_wizard_entry = form.save(commit=False)
            form_wizard_entry.user = request.user
            try:
                form_wizard_entry.save()
                messages.info(
                    request,
                    _('Form wizard {0} was created '
                      'successfully.').format(form_wizard_entry.name)
                )
                return redirect(
                    'fobi.edit_form_wizard_entry',
                    form_wizard_entry_id=form_wizard_entry.pk
                )
            except IntegrityError as err:
                messages.info(
                    request,
                    _('Errors occurred while saving '
                      'the form wizard: {0}.').format(str(err))
                )

    else:
        form = FormWizardEntryForm(request=request)

    context = {'form': form}

    # If given, pass to the template (and override the value set by
    # the context processor.
    if theme:
        context.update({'fobi_theme': theme})

    if not template_name:
        if not theme:
            theme = get_theme(request=request, as_instance=True)
        template_name = theme.create_form_wizard_entry_template

    if versions.DJANGO_GTE_1_10:
        return render(request, template_name, context)
    else:
        return render_to_response(
            template_name, context, context_instance=RequestContext(request)
        )

# **************************************************************************
# *************************** Edit form wizard entry ***********************
# **************************************************************************

edit_form_wizard_entry_permissions = [
    'fobi.change_formwizardentry',

    'fobi.add_formwizardformentry',
    'fobi.delete_formewizardformentry',

    'fobi.add_formhandlerentry',
    'fobi.change_formhandlerentry',
    'fobi.delete_formhandlerentry',
]


@login_required
@permissions_required(satisfy=SATISFY_ANY,
                      perms=edit_form_wizard_entry_permissions)
def edit_form_wizard_entry(request, form_wizard_entry_id, theme=None,
                           template_name=None):
    """Edit form wizard entry.

    :param django.http.HttpRequest request:
    :param int form_wizard_entry_id:
    :param fobi.base.BaseTheme theme: Theme instance.
    :param str template_name:
    :return django.http.HttpResponse:
    """
    try:
        form_wizard_entry = FormWizardEntry._default_manager \
            .select_related('user') \
            .prefetch_related('formwizardformentry_set') \
            .get(pk=form_wizard_entry_id, user__pk=request.user.pk)
    # .prefetch_related('formhandlerentry_set') \
    except ObjectDoesNotExist as err:
        raise Http404(ugettext("Form wizard entry not found."))

    if 'POST' == request.method:
        # The form entry form (does not contain form elements)
        form = FormWizardEntryForm(request.POST, request.FILES,
                                   instance=form_wizard_entry,
                                   request=request)

        if 'ordering' in request.POST:
            form_wizard_form_entry_formset = FormWizardFormEntryFormSet(
                request.POST,
                request.FILES,
                queryset=form_wizard_entry.formwizardformentry_set.all(),
                # prefix = 'form_element'
            )
            # If form elements aren't properly made (developers's fault)
            # there might be problems with saving the ordering - likely
            # in case of hidden elements only. Thus, we want to avoid
            # errors here.
            try:
                if form_wizard_form_entry_formset.is_valid():
                    form_wizard_form_entry_formset.save()
                    messages.info(
                        request,
                        _("Forms ordering edited successfully.")
                    )
                    return redirect(
                        reverse(
                            'fobi.edit_form_wizard_entry',
                            kwargs={
                                'form_wizard_entry_id': form_wizard_entry_id
                            }
                        )
                    )
            except MultiValueDictKeyError as err:
                messages.error(
                    request,
                    _("Errors occurred while trying to change the "
                      "forms ordering!")
                )
                return redirect(
                    reverse(
                        'fobi.edit_form_wizard_entry',
                        kwargs={'form_wizard_entry_id': form_wizard_entry_id}
                    )
                )
        else:
            form_wizard_form_entry_formset = FormWizardFormEntryFormSet(
                queryset=form_wizard_entry.formwizardformentry_set.all(),
                # prefix='form_element'
            )

        if form.is_valid():
            obj = form.save(commit=False)
            obj.user = request.user
            try:
                obj.save()
                messages.info(
                    request,
                    _('Form wizard {0} was edited '
                      'successfully.').format(form_wizard_entry.name)
                )
                return redirect(
                    reverse(
                        'fobi.edit_form_wizard_entry',
                        kwargs={'form_wizard_entry_id': form_wizard_entry_id}
                    )
                )
            except IntegrityError as err:
                messages.info(
                    request,
                    _('Errors occurred while saving '
                      'the form wizard: {0}.').format(str(err))
                )
    else:
        # The form  wizard entry form (does not contain form elements)
        form = FormWizardEntryForm(
            instance=form_wizard_entry,
            request=request
        )

        form_wizard_form_entry_formset = FormWizardFormEntryFormSet(
            queryset=form_wizard_entry.formwizardformentry_set.all(),
            # prefix='form_element'
        )

    # In case of success, we don't need this (since redirect would happen).
    # Thus, fetch only if needed.
    form_wizard_form_entries = form_wizard_entry.formwizardformentry_set \
        .all().select_related('form_entry').order_by('position')[:]
    form_wizard_handlers = form_wizard_entry.formwizardhandlerentry_set \
                                            .all()[:]
    used_form_wizard_handler_uids = [form_wizard_handler.plugin_uid
                                     for form_wizard_handler
                                     in form_wizard_handlers]

    form_wizard_form_entry_ids = [__f.form_entry_id
                                  for __f
                                  in form_wizard_form_entries]
    all_form_entries = FormEntry._default_manager.only('id', 'name', 'slug') \
        .filter(user__pk=request.user.pk) \
        .exclude(id__in=form_wizard_form_entry_ids)

    # List of form handler plugins allowed to user
    user_form_wizard_handler_plugins = get_user_form_wizard_handler_plugins(
        request.user,
        exclude_used_singles=True,
        used_form_wizard_handler_plugin_uids=used_form_wizard_handler_uids
    )

    # If no theme provided, pick a default one.
    if not theme:
        theme = get_theme(request=request, as_instance=True)

    # theme.collect_plugin_media(form_elements)

    context = {
        'form': form,
        'form_wizard_entry': form_wizard_entry,
        'form_wizard_entry_forms': form_wizard_form_entries,
        'form_wizard_handlers': form_wizard_handlers,
        'all_form_entries': all_form_entries,
        'user_form_wizard_handler_plugins': user_form_wizard_handler_plugins,
        'form_wizard_form_entry_formset': form_wizard_form_entry_formset,
        'fobi_theme': theme,
    }

    if not template_name:
        template_name = theme.edit_form_wizard_entry_template

    if versions.DJANGO_GTE_1_10:
        return render(request, template_name, context)
    else:
        return render_to_response(
            template_name, context, context_instance=RequestContext(request)
        )

# *****************************************************************************
# **************************** Delete form wizard entry ***********************
# *****************************************************************************

delete_form_wizard_entry_permissions = [
    'fobi.delete_formwizardentry',
    'fobi.delete_formwizardformentry',
    'fobi.delete_formwizardhandlerentry',
]


@login_required
@permissions_required(satisfy=SATISFY_ALL,
                      perms=delete_form_wizard_entry_permissions)
def delete_form_wizard_entry(request, form_wizard_entry_id,
                             template_name=None):
    """Delete form wizard entry.

    :param django.http.HttpRequest request:
    :param int form_wizard_entry_id:
    :param string template_name:
    :return django.http.HttpResponse:
    """
    try:
        obj = FormWizardEntry._default_manager \
            .get(pk=form_wizard_entry_id, user__pk=request.user.pk)
    except ObjectDoesNotExist as err:
        raise Http404(ugettext("Form wizard entry not found."))

    obj.delete()

    messages.info(
        request,
        _('The form wizard "{0}" was deleted successfully.').format(obj.name)
    )

    return redirect('fobi.form_wizards_dashboard')

# *****************************************************************************
# ************************ View form wizard entry *****************************
# *****************************************************************************


class FormWizardView(DynamicSessionWizardView):
    """Dynamic form wizard."""

    file_storage = FileSystemStorage(
        location=get_wizard_files_upload_dir()
    )

    def get_context_data(self, form, **kwargs):
        """Get context data."""
        context_data = super(FormWizardView, self).get_context_data(
            form=form, **kwargs
        )

        context_data.update({
            'form_wizard_entry': self.form_wizard_entry,
            'form_wizard_mode': True,
            'fobi_theme': self.fobi_theme,
        })

        return context_data

    def get_initial_wizard_data(self, request, *args, **kwargs):
        """Get initial wizard data."""
        try:
            qs_kwargs = {'slug': kwargs.get('form_wizard_entry_slug')}
            if not request.user.is_authenticated():
                kwargs.update({'is_public': True})
            form_wizard_entry = FormWizardEntry.objects \
                .select_related('user') \
                .get(**qs_kwargs)
        except ObjectDoesNotExist as err:
            raise Http404(ugettext("Form wizard entry not found."))

        form_entries = [
            form_wizard_form_entry.form_entry
            for form_wizard_form_entry
            in form_wizard_entry.formwizardformentry_set
                                .all()
                                .select_related('form_entry')
        ]
        form_list = []
        form_entry_mapping = {}
        wizard_form_element_entries = []
        for creation_counter, form_entry in enumerate(form_entries):
            # Using frozen queryset to minimize query usage
            form_element_entries = form_entry.formelemententry_set.all()[:]
            wizard_form_element_entries += form_element_entries
            form_cls = assemble_form_class(
                form_entry,
                request=request,
                form_element_entries=form_element_entries
            )

            form_list.append(
                (form_entry.slug, form_cls)
            )
            form_entry_mapping[form_entry.slug] = form_entry

        if 0 == len(form_list):
            raise Http404(
                ugettext("Form wizard entry does not contain any forms.")
            )

        theme = get_theme(request=request, as_instance=True)
        theme.collect_plugin_media(wizard_form_element_entries)

        return {
            'form_list': form_list,
            'template_name': theme.view_form_wizard_entry_template,
            'form_wizard_entry': form_wizard_entry,
            'wizard_form_element_entries': wizard_form_element_entries,
            'form_entry_mapping': form_entry_mapping,
            'fobi_theme': theme,
        }

    def render_done(self, form, **kwargs):
        """Render done.

        This method gets called when all forms passed. The method should also
        re-validate all steps to prevent manipulation. If any form fails to
        validate, `render_revalidation_failure` should get called.
        If everything is fine call `done`.
        """
        final_forms = OrderedDict()
        # walk through the form list and try to validate the data again.
        for form_key in self.get_form_list():

            form_obj = self.get_form(
                step=form_key,
                data=self.storage.get_step_data(form_key),
                files=self.storage.get_step_files(form_key)
            )

            if not form_obj.is_valid():
                return self.render_revalidation_failure(form_key,
                                                        form_obj,
                                                        **kwargs)

            # Fire plugin processors
            form_entry = self.form_entry_mapping[form_key]
            form_obj = submit_plugin_form_data(
                form_entry=form_entry,
                request=self.request,
                form=form_obj
            )

            final_forms[form_key] = form_obj

        # render the done view and reset the wizard before returning the
        # response. This is needed to prevent from rendering done with the
        # same data twice.
        done_response = self.done(final_forms.values(),
                                  form_dict=final_forms,
                                  **kwargs)
        self.storage.reset()
        return done_response

    def done(self, form_list, **kwargs):
        """Done."""
        try:
            qs_kwargs = {'slug': kwargs.get('form_wizard_entry_slug')}
            if not self.request.user.is_authenticated():
                kwargs.update({'is_public': True})
            form_wizard_entry = FormWizardEntry.objects \
                .select_related('user') \
                .get(**qs_kwargs)
        except ObjectDoesNotExist as err:
            raise Http404(ugettext("Form wizard entry not found."))

        # Run all handlers
        handler_responses, handler_errors = run_form_wizard_handlers(
            form_wizard_entry=form_wizard_entry,
            request=self.request,
            form_list=form_list,
            form_wizard=self,
            form_element_entries=self.wizard_form_element_entries
        )

        # do_something_with_the_form_data(form_list)
        redirect_url = reverse('fobi.form_wizard_entry_submitted',
                               args=[form_wizard_entry.slug])
        return HttpResponseRedirect(redirect_url)

# *****************************************************************************
# ************************** View form wizard entry success *******************
# *****************************************************************************


def form_wizard_entry_submitted(request, form_wizard_entry_slug=None,
                                template_name=None):
    """Form wizard entry submitted.

    :param django.http.HttpRequest request:
    :param string form_wizard_entry_slug:
    :param string template_name:
    :return django.http.HttpResponse:
    """
    try:
        kwargs = {'slug': form_wizard_entry_slug}
        if not request.user.is_authenticated():
            kwargs.update({'is_public': True})
        form_wizard_entry = FormWizardEntry._default_manager \
            .select_related('user') \
            .get(**kwargs)
    except ObjectDoesNotExist as err:
        raise Http404(ugettext("Form wizard entry not found."))

    context = {
        'form_wizard_entry_slug': form_wizard_entry_slug,
        'form_wizard_entry': form_wizard_entry
    }

    if not template_name:
        theme = get_theme(request=request, as_instance=True)
        template_name = theme.form_wizard_entry_submitted_template

    if versions.DJANGO_GTE_1_10:
        return render(request, template_name, context)
    else:
        return render_to_response(
            template_name, context, context_instance=RequestContext(request)
        )

# *****************************************************************************
# *****************************************************************************
# **************************** Form wizard form entry *************************
# *****************************************************************************
# *****************************************************************************

# *****************************************************************************
# ************************* Add form wizard form entry ************************
# *****************************************************************************


@login_required
@permission_required('fobi.add_formwizardformentry')
def add_form_wizard_form_entry(request,
                               form_wizard_entry_id,
                               form_entry_id,
                               theme=None,
                               template_name=None):
    """Add form wizard form entry.

    :param django.http.HttpRequest request:
    :param int form_wizard_entry_id:
    :param int form_entry_id:
    :param fobi.base.BaseTheme theme: Theme instance.
    :param string template_name:
    :return django.http.HttpResponse:
    """
    try:
        form_wizard_entry = FormWizardEntry.objects.get(
            pk=form_wizard_entry_id,
            user=request.user
        )
    except ObjectDoesNotExist as err:
        raise Http404(ugettext("Form wizard entry not found."))

    try:
        form_entry = FormEntry.objects.get(
            pk=form_entry_id,
            user=request.user
        )
    except ObjectDoesNotExist as err:
        raise Http404(ugettext("Form entry not found."))

    try:
        obj = FormWizardFormEntry.objects.create(
            form_wizard_entry=form_wizard_entry,
            form_entry=form_entry
        )
    except IntegrityError as err:
        messages.error(
            request,
            _('The form entry "{0}" could not be added to the wizard "{1}" '
              'due to the following error "{2}".').format(
                form_entry.name,
                form_wizard_entry.name,
                str(err)
            )
        )
        return redirect(
            "{0}?active_tab=tab-form-elements".format(
                reverse(
                    'fobi.edit_form_wizard_entry',
                    kwargs={
                        'form_wizard_entry_id': form_wizard_entry_id
                    }
                )
            )
        )

    # Handling the position
    position = 1
    records = FormWizardFormEntry.objects.filter(
        form_wizard_entry_id=form_wizard_entry_id,
        # form_entry_id=form_entry_id
    ).aggregate(models.Max('position'))
    if records:
        try:
            position = records['{0}__max'.format('position')] + 1

        except TypeError as err:
            pass

    obj.position = position

    # Save the object.
    obj.save()

    messages.info(
        request,
        _('The form entry "{0}" was added '
          'successfully to the wizard "{1}".').format(
            form_entry.name,
            form_wizard_entry.name
        )
    )
    return redirect(
        "{0}?active_tab=tab-form-elements".format(
            reverse(
                'fobi.edit_form_wizard_entry',
                kwargs={
                    'form_wizard_entry_id': form_wizard_entry_id
                }
            )
        )
    )

# *****************************************************************************
# ************************** Delete form wizard form entry ********************
# *****************************************************************************


@login_required
@permission_required('fobi.delete_formwizardformentry')
def delete_form_wizard_form_entry(request, form_wizard_form_entry_id):
    """Delete form wizard form entry.

    :param django.http.HttpRequest request:
    :param int form_wizard_form_entry_id:
    :return django.http.HttpResponse:
    """
    try:
        obj = FormWizardFormEntry \
                ._default_manager \
                .select_related('form_wizard_entry') \
                .get(pk=form_wizard_form_entry_id,
                     form_wizard_entry__user__pk=request.user.pk)
    except ObjectDoesNotExist as err:
        raise Http404(_("{0} not found."
                        "").format(FormWizardFormEntry._meta.verbose_name))

    form_wizard_entry_id = obj.form_wizard_entry_id
    obj.delete()

    messages.info(
        request,
        'The form wizard form entry "{0}" was deleted successfully.'.format(
            obj.form_wizard_entry.name
        )
    )

    redirect_url = reverse(
        'fobi.edit_form_wizard_entry',
        kwargs={'form_wizard_entry_id': form_wizard_entry_id}
    )
    return redirect(
        "{0}{1}".format(redirect_url, '?active_tab=tab-form-elements')
    )

# *****************************************************************************
# *****************************************************************************
# *************************** Form wizard form handler ************************
# *****************************************************************************
# *****************************************************************************

# *****************************************************************************
# **************************** Add form handler entry *************************
# *****************************************************************************


@login_required
@permission_required('fobi.add_formwizardhandlerentry')
def add_form_wizard_handler_entry(request,
                                  form_wizard_entry_id,
                                  form_wizard_handler_plugin_uid,
                                  theme=None,
                                  template_name=None):
    """Add form handler entry.

    :param django.http.HttpRequest request:
    :param int form_entry_id:
    :param int form_handler_plugin_uid:
    :param fobi.base.BaseTheme theme: Theme instance.
    :param string template_name:
    :return django.http.HttpResponse:
    """
    try:
        form_wizard_entry = FormWizardEntry._default_manager.get(
            pk=form_wizard_entry_id
        )
    except ObjectDoesNotExist as err:
        raise Http404(ugettext("Form wizard entry not found."))

    user_form_wizard_handler_plugin_uids = \
        get_user_form_wizard_handler_plugin_uids(
            request.user
        )

    if form_wizard_handler_plugin_uid not \
            in user_form_wizard_handler_plugin_uids:
        raise Http404(ugettext("Plugin does not exist or you are not allowed "
                               "to use this plugin!"))

    FormWizardHandlerPlugin = form_wizard_handler_plugin_registry.get(
        form_wizard_handler_plugin_uid
    )

    # Check if we deal with form handler plugin that is only allowed to be
    # used once. In that case, check if it has been used already in the current
    # form entry.
    if not FormWizardHandlerPlugin.allow_multiple:
        times_used = FormWizardHandlerEntry._default_manager \
            .filter(form_wizard_entry__id=form_wizard_entry_id,
                    plugin_uid=FormWizardHandlerPlugin.uid) \
            .count()
        if times_used > 0:
            raise Http404(
                ugettext("The {0} plugin can be used only once in a "
                         "form.").format(FormWizardHandlerPlugin.name)
            )

    form_wizard_handler_plugin = FormWizardHandlerPlugin(user=request.user)
    form_wizard_handler_plugin.request = request

    FormWizardHandlerPluginForm = form_wizard_handler_plugin.get_form()
    form = None

    obj = FormWizardHandlerEntry()
    obj.form_wizard_entry = form_wizard_entry
    obj.plugin_uid = form_wizard_handler_plugin_uid
    obj.user = request.user

    save_object = False

    if not FormWizardHandlerPluginForm:
        save_object = True

    elif 'POST' == request.method:
        form = form_wizard_handler_plugin.get_initialised_create_form_or_404(
            data=request.POST,
            files=request.FILES
        )
        if form.is_valid():
            # Saving the plugin form data.
            form.save_plugin_data(request=request)

            # Getting the plugin data.
            obj.plugin_data = form.get_plugin_data(request=request)

            save_object = True

    else:
        form = form_wizard_handler_plugin.get_initialised_create_form_or_404()

    if save_object:
        # Save the object.
        obj.save()

        messages.info(
            request,
            _('The form wizard handler plugin "{0}" was added '
              'successfully.').format(form_wizard_handler_plugin.name)
        )
        return redirect(
            "{0}?active_tab=tab-form-handlers".format(
                reverse(
                    'fobi.edit_form_wizard_entry',
                    kwargs={'form_wizard_entry_id': form_wizard_entry_id}
                )
            )
        )

    context = {
        'form': form,
        'form_wizard_entry': form_wizard_entry,
        'form_wizard_handler_plugin': form_wizard_handler_plugin,
    }

    # If given, pass to the template (and override the value set by
    # the context processor.
    if theme:
        context.update({'fobi_theme': theme})

    if not template_name:
        if not theme:
            theme = get_theme(request=request, as_instance=True)
        template_name = theme.add_form_wizard_handler_entry_template

    if versions.DJANGO_GTE_1_10:
        return render(request, template_name, context)
    else:
        return render_to_response(
            template_name, context, context_instance=RequestContext(request)
        )

# *****************************************************************************
# ************************ Edit form wizard handler entry *********************
# *****************************************************************************


@login_required
@permission_required('fobi.change_formwizardhandlerentry')
def edit_form_wizard_handler_entry(request,
                                   form_wizard_handler_entry_id,
                                   theme=None,
                                   template_name=None):
    """Edit form handler entry.

    :param django.http.HttpRequest request:
    :param int form_handler_entry_id:
    :param fobi.base.BaseTheme theme: Theme instance.
    :param string template_name:
    :return django.http.HttpResponse:
    """
    try:
        obj = FormWizardHandlerEntry._default_manager \
            .select_related('form_wizard_entry') \
            .get(pk=form_wizard_handler_entry_id)
    except ObjectDoesNotExist as err:
        raise Http404(ugettext("Form wizard handler entry not found."))

    form_wizard_entry = obj.form_wizard_entry

    form_wizard_handler_plugin = obj.get_plugin(request=request)
    form_wizard_handler_plugin.request = request

    FormWizardHandlerPluginForm = form_wizard_handler_plugin.get_form()
    form = None

    if not FormWizardHandlerPluginForm:
        messages.info(
            request,
            _('The form wizard handler plugin "{0}" is not '
              'configurable!').format(form_wizard_handler_plugin.name)
        )
        return redirect(
            'fobi.edit_form_wizard_entry',
            form_wizard_entry_id=form_wizard_entry.pk
        )

    elif 'POST' == request.method:
        form = form_wizard_handler_plugin.get_initialised_edit_form_or_404(
            data=request.POST,
            files=request.FILES
        )

        if form.is_valid():
            # Saving the plugin form data.
            form.save_plugin_data(request=request)

            # Getting the plugin data.
            obj.plugin_data = form.get_plugin_data(request=request)

            # Save the object.
            obj.save()

            messages.info(
                request,
                _('The form wizard handler plugin "{0}" was edited '
                  'successfully.').format(form_wizard_handler_plugin.name)
            )

            return redirect('fobi.edit_form_wizard_entry',
                            form_wizard_entry_id=form_wizard_entry.pk)

    else:
        form = form_wizard_handler_plugin.get_initialised_edit_form_or_404()

    context = {
        'form': form,
        'form_wizard_entry': form_wizard_entry,
        'form_wizard_handler_plugin': form_wizard_handler_plugin,
    }

    # If given, pass to the template (and override the value set by
    # the context processor.
    if theme:
        context.update({'fobi_theme': theme})

    if not template_name:
        if not theme:
            theme = get_theme(request=request, as_instance=True)
        template_name = theme.edit_form_handler_entry_template

    if versions.DJANGO_GTE_1_10:
        return render(request, template_name, context)
    else:
        return render_to_response(
            template_name, context, context_instance=RequestContext(request)
        )

# *****************************************************************************
# *********************** Delete form wizard handler entry ********************
# *****************************************************************************


@login_required
@permission_required('fobi.delete_formwizardhandlerentry')
def delete_form_wizard_handler_entry(request, form_wizard_handler_entry_id):
    """Delete form handler entry.

    :param django.http.HttpRequest request:
    :param int form_wizard_handler_entry_id:
    :return django.http.HttpResponse:
    """
    return _delete_wizard_plugin_entry(
        request=request,
        entry_id=form_wizard_handler_entry_id,
        EntryModel=FormWizardHandlerEntry,
        get_user_plugin_uids_func=get_user_form_wizard_handler_plugin_uids,
        message=_(
            'The form wizard handler plugin "{0}" was deleted successfully.'),
        html_anchor='?active_tab=tab-form-handlers'
    )

# *****************************************************************************
# *****************************************************************************
# ******************************** View form entry ****************************
# *****************************************************************************
# *****************************************************************************

# *****************************************************************************
# ******************************** View form entry ****************************
# *****************************************************************************


def view_form_entry(request, form_entry_slug, theme=None, template_name=None):
    """View created form.

    :param django.http.HttpRequest request:
    :param string form_entry_slug:
    :param fobi.base.BaseTheme theme: Theme instance.
    :param string template_name:
    :return django.http.HttpResponse:
    """
    try:
        kwargs = {'slug': form_entry_slug}
        if not request.user.is_authenticated():
            kwargs.update({'is_public': True})
        form_entry = FormEntry._default_manager.select_related('user') \
                              .get(**kwargs)
    except ObjectDoesNotExist as err:
        raise Http404(ugettext("Form entry not found."))

    form_element_entries = form_entry.formelemententry_set.all()[:]

    # This is where the most of the magic happens. Our form is being built
    # dynamically.
    FormClass = assemble_form_class(
        form_entry,
        form_element_entries=form_element_entries,
        request=request
    )

    if 'POST' == request.method:
        form = FormClass(request.POST, request.FILES)

        # Fire pre form validation callbacks
        fire_form_callbacks(form_entry=form_entry, request=request, form=form,
                            stage=CALLBACK_BEFORE_FORM_VALIDATION)

        if form.is_valid():
            # Fire form valid callbacks, before handling submitted plugin
            # form data.
            form = fire_form_callbacks(
                form_entry=form_entry,
                request=request,
                form=form,
                stage=CALLBACK_FORM_VALID_BEFORE_SUBMIT_PLUGIN_FORM_DATA
            )

            # Fire plugin processors
            form = submit_plugin_form_data(form_entry=form_entry,
                                           request=request, form=form)

            # Fire form valid callbacks
            form = fire_form_callbacks(form_entry=form_entry,
                                       request=request, form=form,
                                       stage=CALLBACK_FORM_VALID)

            # Run all handlers
            handler_responses, handler_errors = run_form_handlers(
                form_entry=form_entry,
                request=request,
                form=form,
                form_element_entries=form_element_entries
            )

            # Warning that not everything went ok.
            if handler_errors:
                for handler_error in handler_errors:
                    messages.warning(
                        request,
                        _("Error occurred: {0}."
                          "").format(handler_error)
                    )

            # Fire post handler callbacks
            fire_form_callbacks(
                form_entry=form_entry,
                request=request,
                form=form,
                stage=CALLBACK_FORM_VALID_AFTER_FORM_HANDLERS
            )

            messages.info(
                request,
                _("Form {0} was submitted successfully."
                  "").format(form_entry.name)
            )
            return redirect(
                reverse('fobi.form_entry_submitted', args=[form_entry.slug])
            )
        else:
            # Fire post form validation callbacks
            fire_form_callbacks(form_entry=form_entry, request=request,
                                form=form, stage=CALLBACK_FORM_INVALID)

    else:
        # Providing initial form data by feeding entire GET dictionary
        # to the form, if ``GET_PARAM_INITIAL_DATA`` is present in the
        # GET.
        kwargs = {}
        if GET_PARAM_INITIAL_DATA in request.GET:
            kwargs = {'initial': request.GET}
        form = FormClass(**kwargs)

    # In debug mode, try to identify possible problems.
    if DEBUG:
        form.as_p()
    else:
        try:
            form.as_p()
        except Exception as err:
            logger.error(err)

    theme = get_theme(request=request, as_instance=True)
    theme.collect_plugin_media(form_element_entries)

    context = {
        'form': form,
        'form_entry': form_entry,
        'fobi_theme': theme,
    }

    if not template_name:
        template_name = theme.view_form_entry_template

    if versions.DJANGO_GTE_1_10:
        return render(request, template_name, context)
    else:
        return render_to_response(
            template_name, context, context_instance=RequestContext(request)
        )

# *****************************************************************************
# **************************** View form entry success ************************
# *****************************************************************************


def form_entry_submitted(request, form_entry_slug=None, template_name=None):
    """Form entry submitted.

    :param django.http.HttpRequest request:
    :param string form_entry_slug:
    :param string template_name:
    :return django.http.HttpResponse:
    """
    try:
        kwargs = {'slug': form_entry_slug}
        if not request.user.is_authenticated():
            kwargs.update({'is_public': True})
        form_entry = FormEntry._default_manager \
            .select_related('user') \
            .get(**kwargs)
    except ObjectDoesNotExist as err:
        raise Http404(ugettext("Form entry not found."))

    # try:
    #     form_entry = FormEntry._default_manager.get(slug=form_entry_slug,
    #                                                 user__pk=request.user.pk)
    # except ObjectDoesNotExist as err:
    #     raise Http404(ugettext("Form entry not found."))

    context = {
        'form_entry_slug': form_entry_slug,
        'form_entry': form_entry
    }

    if not template_name:
        theme = get_theme(request=request, as_instance=True)
        template_name = theme.form_entry_submitted_template

    if versions.DJANGO_GTE_1_10:
        return render(request, template_name, context)
    else:
        return render_to_response(
            template_name, context, context_instance=RequestContext(request)
        )

# *****************************************************************************
# *****************************************************************************
# **************************** Export form entry ******************************
# *****************************************************************************
# *****************************************************************************


@login_required
@permissions_required(satisfy=SATISFY_ALL, perms=create_form_entry_permissions)
def export_form_entry(request, form_entry_id, template_name=None):
    """Export form entry to JSON.

    :param django.http.HttpRequest request:
    :param int form_entry_id:
    :param string template_name:
    :return django.http.HttpResponse:
    """
    try:
        form_entry = FormEntry._default_manager \
                              .get(pk=form_entry_id, user__pk=request.user.pk)

    except ObjectDoesNotExist as err:
        raise Http404(ugettext("Form entry not found."))

    data = {
        'name': form_entry.name,
        'slug': form_entry.slug,
        'is_public': False,
        'is_cloneable': False,
        # 'position': form_entry.position,
        'success_page_title': form_entry.success_page_title,
        'success_page_message': form_entry.success_page_message,
        'action': form_entry.action,
        'form_elements': [],
        'form_handlers': [],
    }

    form_element_entries = form_entry.formelemententry_set.all()[:]
    form_handler_entries = form_entry.formhandlerentry_set.all()[:]

    for form_element_entry in form_element_entries:
        data['form_elements'].append(
            {
                'plugin_uid': form_element_entry.plugin_uid,
                'position': form_element_entry.position,
                'plugin_data': form_element_entry.plugin_data,
            }
        )

    for form_handler_entry in form_handler_entries:
        data['form_handlers'].append(
            {
                'plugin_uid': form_handler_entry.plugin_uid,
                'plugin_data': form_handler_entry.plugin_data,
            }
        )

    data_exporter = JSONDataExporter(json.dumps(data), form_entry.slug)

    return data_exporter.export()

# *****************************************************************************
# *****************************************************************************
# **************************** Import form entry ******************************
# *****************************************************************************
# *****************************************************************************


@login_required
@permissions_required(satisfy=SATISFY_ALL, perms=create_form_entry_permissions)
def import_form_entry(request, template_name=None):
    """Import form entry.

    :param django.http.HttpRequest request:
    :param string template_name:
    :return django.http.HttpResponse:
    """
    if 'POST' == request.method:
        form = ImportFormEntryForm(request.POST, request.FILES)

        if form.is_valid():
            # Reading the contents of the file into JSON
            json_file = form.cleaned_data['file']
            file_contents = json_file.read()

            # This is the form data which we are going to use when recreating
            # the form.
            form_data = json.loads(file_contents)

            # Since we just feed all the data to the `FormEntry` class,
            # we need to make sure it doesn't have strange fields in.
            # Furthermore, we will use the `form_element_data` and
            # `form_handler_data` for filling the missing plugin data.
            form_elements_data = form_data.pop('form_elements', [])
            form_handlers_data = form_data.pop('form_handlers', [])

            form_data_keys_whitelist = (
                'name',
                'slug',
                'is_public',
                'is_cloneable',
                # 'position',
                'success_page_title',
                'success_page_message',
                'action',
            )

            # In this way we keep possible trash out.
            for key in form_data.keys():
                if key not in form_data_keys_whitelist:
                    form_data.pop(key)

            # User information we always recreate!
            form_data['user'] = request.user

            form_entry = FormEntry(**form_data)

            form_entry.name += ugettext(" (imported on {0})").format(
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            form_entry.save()

            # One by one, importing form element plugins.
            for form_element_data in form_elements_data:
                if form_element_plugin_registry._registry.get(
                        form_element_data.get('plugin_uid', None), None):
                    form_element = FormElementEntry(**form_element_data)
                    form_element.form_entry = form_entry
                    form_element.save()
                else:
                    if form_element_data.get('plugin_uid', None):
                        messages.warning(
                            request,
                            _('Plugin {0} is missing in the system.'
                              '').format(form_element_data.get('plugin_uid'))
                        )
                    else:
                        messages.warning(
                            request,
                            _('Some essential plugin data missing in the JSON '
                              'import.')
                        )

            # One by one, importing form handler plugins.
            for form_handler_data in form_handlers_data:
                if form_handler_plugin_registry._registry.get(
                        form_handler_data.get('plugin_uid', None), None):
                    form_handler = FormHandlerEntry(**form_handler_data)
                    form_handler.form_entry = form_entry
                    form_handler.save()
                else:
                    if form_handler.get('plugin_uid', None):
                        messages.warning(
                            request,
                            _('Plugin {0} is missing in the system.'
                              '').format(form_handler.get('plugin_uid'))
                        )
                    else:
                        messages.warning(
                            request,
                            _('Some essential data missing in the JSON '
                              'import.')
                        )

            messages.info(
                request,
                _('The form was imported successfully.')
            )
            return redirect(
                'fobi.edit_form_entry', form_entry_id=form_entry.pk
            )
    else:
        form = ImportFormEntryForm()

    # When importing entries from saved JSON we shouldn't just save
    # them into database and consider it done, since there might be cases
    # if a certain plugin doesn't exist in the system, which will lead
    # to broken form entries. Instead, we should check every single
    # form-element or form-handler plugin for existence. If not doesn't exist
    # in the system, we might: (1) roll entire transaction back or (2) ignore
    # broken entries. The `ImportFormEntryForm` form has two fields to
    # additional fields which serve the purpose:
    # `ignore_broken_form_element_entries` and
    # `ignore_broken_form_handler_entries`. When set to True, when a broken
    # form element/handler plugin has been discovered, the import would
    # continue, having the broken form element/handler entries not imported.

    context = {
        'form': form,
        # 'form_entry': form_entry
    }

    if not template_name:
        theme = get_theme(request=request, as_instance=True)
        template_name = theme.import_form_entry_template

    if versions.DJANGO_GTE_1_10:
        return render(request, template_name, context)
    else:
        return render_to_response(
            template_name, context, context_instance=RequestContext(request)
        )

# *****************************************************************************
# *****************************************************************************
# ****************************** Form importers *******************************
# *****************************************************************************
# *****************************************************************************


@login_required
@permissions_required(satisfy=SATISFY_ALL, perms=create_form_entry_permissions)
def form_importer(request,
                  form_importer_plugin_uid,
                  template_name=None,
                  *args,
                  **kwargs):
    """Form importer.

    :param django.http.HttpRequest request:
    :param str form_importer_plugin_uid:
    :param str template_name:
    """
    ensure_importers_autodiscover()
    form_importer_cls = form_importer_plugin_registry._registry.get(
        form_importer_plugin_uid
    )
    form_importer = form_importer_cls(form_entry_cls=FormEntry,
                                      form_element_entry_cls=FormElementEntry)

    return form_importer.get_wizard(request, *args, **kwargs)
