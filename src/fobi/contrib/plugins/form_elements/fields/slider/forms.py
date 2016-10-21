from django import forms
from django.utils.translation import ugettext_lazy as _

from fobi.base import BaseFormFieldPluginForm, get_theme

from .constants import (
    SLIDER_DEFAULT_TOOLTIP,
    SLIDER_DEFAULT_HANDLE,
    SLIDER_DEFAULT_SHOW_ENDPOINTS_AS,
    SLIDER_TOOLTIP_CHOICES,
    SLIDER_HANDLE_CHOICES,
    SLIDER_SHOW_ENDPOINTS_AS_CHOICES,
    SLIDER_HANDLE_TRIANGLE,
    SLIDER_HANDLE_CUSTOM,
    SLIDER_SHOW_ENDPOINTS_AS_LABELED_TICKS,
    SLIDER_SHOW_ENDPOINTS_AS_TICKS
)

from .settings import INITIAL, MAX_VALUE, MIN_VALUE, STEP

__title__ = 'fobi.contrib.plugins.form_elements.fields.slider.forms'
__author__ = 'Artur Barseghyan <artur.barseghyan@gmail.com>'
__copyright__ = '2014-2015 Artur Barseghyan'
__license__ = 'GPL 2.0/LGPL 2.1'
__all__ = ('SliderInputForm',)

theme = get_theme(request=None, as_instance=True)


class SliderInputForm(forms.Form, BaseFormFieldPluginForm):
    """Form for ``SliderPercentageInputPlugin``."""

    plugin_data_fields = [
        ("label", ""),
        ("name", ""),
        ("min_value", MIN_VALUE),
        ("max_value", MAX_VALUE),
        ("step", STEP),
        ("tooltip", SLIDER_DEFAULT_TOOLTIP),
        ("handle", SLIDER_DEFAULT_HANDLE),
        # ("disable_slider_background", False),
        ("show_endpoints_as", SLIDER_DEFAULT_SHOW_ENDPOINTS_AS),
        ("label_start", ""),
        ("label_end", ""),
        # ("custom_ticks", ""),
        ("help_text", ""),
        ("initial", INITIAL),
        ("required", False)
    ]

    label = forms.CharField(
        label=_("Label"),
        required=True,
        widget=forms.widgets.TextInput(
            attrs={'class': theme.form_element_html_class}
        )
    )
    name = forms.CharField(
        label=_("Name"),
        required=True,
        widget=forms.widgets.TextInput(
            attrs={'class': theme.form_element_html_class}
        )
    )
    min_value = forms.IntegerField(
        label=_("Min value"),
        required=True,
        widget=forms.widgets.TextInput(
            attrs={'class': theme.form_element_html_class}
        ),
        min_value=MIN_VALUE,
        max_value=MAX_VALUE
    )
    max_value = forms.IntegerField(
        label=_("Max value"),
        required=True,
        widget=forms.widgets.TextInput(
            attrs={'class': theme.form_element_html_class}
        ),
        min_value=MIN_VALUE,
        max_value=MAX_VALUE
    )
    step = forms.IntegerField(
        label=_("Step"),
        required=True,
        help_text=_("Step size"),
        widget=forms.widgets.TextInput(
            attrs={'class': theme.form_element_html_class}
        ),
        min_value=MIN_VALUE,
        max_value=MAX_VALUE
    )
    tooltip = forms.ChoiceField(
        label=_("Tooltip"),
        choices=SLIDER_TOOLTIP_CHOICES,
        required=False,
        widget=forms.widgets.Select(
            attrs={'class': theme.form_element_html_class}
        )
    )
    handle = forms.ChoiceField(
        label=_("Handle"),
        choices=SLIDER_HANDLE_CHOICES,
        required=False,
        widget=forms.widgets.Select(
            attrs={'class': theme.form_element_html_class}
        )
    )
    # disable_slider_background = forms.BooleanField(
    #     label=_("Disable slider background"),
    #     required=False,
    #     widget=forms.widgets.CheckboxInput(
    #         attrs={'class': theme.form_element_checkbox_html_class}
    #     )
    # )
    show_endpoints_as = forms.ChoiceField(
        label=_("Show endpoints as"),
        choices=SLIDER_SHOW_ENDPOINTS_AS_CHOICES,
        required=False,
        widget=forms.widgets.Select(
            attrs={'class': theme.form_element_html_class}
        )
    )
    label_start = forms.CharField(
        label=_("Start label"),
        help_text=_("Start endpoint label"),
        required=False,
        widget=forms.widgets.TextInput(
            attrs={'class': theme.form_element_html_class}
        )
    )
    label_end = forms.CharField(
        label=_("End label"),
        help_text=_("End endpoint label"),
        required=False,
        widget=forms.widgets.TextInput(
            attrs={'class': theme.form_element_html_class}
        )
    )
    # custom_ticks = forms.CharField(
    #     label=_("Custom ticks"),
    #     required=False,
    #     help_text=_("Enter single values/pairs per line. Example:<code><br/>"
    #                 "&nbsp;&nbsp;&nbsp;&nbsp;1<br/>"
    #                 "&nbsp;&nbsp;&nbsp;&nbsp;2<br/>"
    #                 "&nbsp;&nbsp;&nbsp;&nbsp;3, Alpha<br/>"
    #                 "&nbsp;&nbsp;&nbsp;&nbsp;4, Beta<br/>"
    #                 "</code><br/>"
    #                 "It finally transforms into the following HTML "
    #                 "code:<code><br/>"
    #                 '&nbsp;&nbsp;&nbsp;&nbsp;'
    #                 'data-slider-ticks="[1, 2, 3, 4]"<br/>'
    #                 '&nbsp;&nbsp;&nbsp;&nbsp;'
    #                 "data-slider-ticks-labels='"
    #                 '["1", "2", "Alpha", "Beta"]'
    #                 "'</code>"),
    #     widget=forms.widgets.Textarea(
    #         attrs={'class': theme.form_element_html_class}
    #     )
    # )
    help_text = forms.CharField(
        label=_("Help text"),
        required=False,
        widget=forms.widgets.TextInput(
            attrs={'class': theme.form_element_html_class}
        )
    )
    initial = forms.IntegerField(
        label=_("Initial"),
        required=False,
        widget=forms.widgets.TextInput(
            attrs={'class': theme.form_element_html_class}
        ),
        min_value=MIN_VALUE,
        max_value=MAX_VALUE,
        initial=INITIAL
    )
    required = forms.BooleanField(
        label=_("Required"),
        required=False,
        widget=forms.widgets.CheckboxInput(
            attrs={'class': theme.form_element_checkbox_html_class}
        )
    )

    def clean(self):
        """Validating the values."""
        super(SliderInputForm, self).clean()

        max_value = self.cleaned_data['max_value']
        min_value = self.cleaned_data['min_value']
        initial = self.cleaned_data['initial']
        step = self.cleaned_data['step']
        show_endpoints_as = self.cleaned_data['show_endpoints_as']
        handle = self.cleaned_data['handle']

        if max_value < min_value:
            self.add_error(
                'max_value',
                _("`max_value` should be > than `min_value`.")
            )

        if step > max_value - min_value:
            self.add_error(
                'step',
                _("`step` should be > than `max_value` - `min_value`.")
            )

        if max_value < initial:
            self.add_error(
                'initial',
                _("`max_value` should be >= than `initial`.")
            )

        if min_value > initial:
            self.add_error(
                'min_value',
                _("`initial` should be >= than `min_value`.")
            )

        label_handles = (SLIDER_HANDLE_TRIANGLE, SLIDER_HANDLE_CUSTOM)
        tick_endpoints = (
            SLIDER_SHOW_ENDPOINTS_AS_LABELED_TICKS,
            SLIDER_SHOW_ENDPOINTS_AS_TICKS
        )
        if handle in label_handles and show_endpoints_as in tick_endpoints:
            self.add_error(
                'handle',
                _("You are not allowed to use Triangle or Custom handles "
                  "with ticks enabled.")
            )
