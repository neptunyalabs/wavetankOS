# from piplates import DACC

import datetime

import dash
from dash import dcc, html, dash_table
import dash_daq as daq

from waveware.config import *
from waveware.app_comps import *
from dash.dependencies import Input, Output,State
import sys

import time
import plotly
import plotly.express as px
import numpy as np
import pandas as pd
pd.options.plotting.backend = "plotly"

log.info(sys.executable)
import logging
import requests

from decimal import *

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dash-comp")

nept_bk1 = "#061E44"
nept_bk2= '#9FBFFF'
triton_bk = "#082255"

app_color = {"graph_bg": triton_bk, "graph_line": "#007ACE"}
btn_header = {
        "background-color": "#FFFFFF",
        "margin": "10 10 0 0px",
        "text-align": "center"
            }

PLOTS = []

max_ts = 0


#parameter groupings
z_wave_parms = ['z_cur','z_cmd','z_wave','v_cur','v_cmd','v_wave']
z_sensors = [f'z{i+1}' for i in range(4)]
e_sensors = [f'e{i+1}' for i in range(4)]

wave_drive_modes = ['stop','center','wave']
M = len(wave_drive_modes)
mode_dict = {i:v.upper() for i,v in enumerate(wave_drive_modes)}

wave_inputs = ['mode','wave-ts','wave-hs','z_ref','z_range','trq_lim']
Ninputs = len(wave_inputs)

all_sys_vars = z_wave_parms+z_sensors+e_sensors #output only
all_sys_parms = z_wave_parms+z_sensors+e_sensors+wave_inputs

# mode_input_parms = dict(
#                             name="Mode".upper(),
#                             id="mode-slider",
#                             type="radio",
#                             min=0,
#                             max=len(wave_drive_modes)-1,
#                             value=0,
#                             step=None,
#                             marks=mode_dict,
#                             tooltip={
#                                     "always_visible": True,
#                                     "placement": "left",
#                                     "template": "{value}"
#                                 },
#                             N=Ninputs
#                         )

mode_input_parms = dict(
                         stop=   {
                                    "label": html.Div(['OFF'], style={'color': 'WHITE', 'font-size': 20}),
                                    "value": "OFF",
                                },
                        center= {
                                    "label": html.Div(['CENTER'], style={'color': 'WHITE', 'font-size': 20}),
                                    "value": "CENTER",
                                },
                        wave  = {
                                    "label": html.Div(['WAVE'], style={'color': 'Red', 'font-size': 20}),
                                    "value": "WAVE",
                                },
                        )

wave_input_parms = { 
                    'wave-ts':dict(
                            name="Ts".upper(),
                            id="wave-ts",
                            type="number",
                            min=1,
                            max=10,
                            value=10,
                            step=0.1,
                            vertical=True,
                            N=Ninputs
                        ),
                    'wave-hs':dict(
                            name="Hs".upper(),
                            id="wave-hs",
                            type="number",
                            min=0,
                            max=0.2,
                            value=0,
                            marks=None,
                            step=0.01,
                            vertical=True,
                            N=Ninputs
                        ),
                        'z_ref':dict(
                            name="z0".upper(),
                            id="z-ref",
                            type="number",
                            min=0,
                            max=100,
                            value=50,
                            step=1,
                            vertical=True,
                            N=Ninputs
                        ),
                        'z_range':dict(
                            name="range".upper(),
                            id="z-range",
                            type="range",
                            min=0,
                            max=100,
                            verticalHeight=250,#px
                            value=[33,66],
                            step=1,
                            vertical=True,
                            N=Ninputs
                        ),
                        'trq_lim':dict(
                            name="Torque".upper(),
                            id="max-torque",
                            type="number",
                            min=0,
                            max=100,
                            value=0,
                            step=1,
                            marks=None,
                            vertical=True,
                            N=Ninputs
                        ), 
                                               
                    }

def generate_plot(title, id=None):

    mark = id if id else title.lower().split("(")[0].strip().replace(" ", "-")
    PLOTS.append(mark)
    o = html.Div(
        [
            html.Div([html.H6(title.upper(), className="graph__title")]),
            dcc.Graph(
                id=f"{mark}-graph",
                figure=dict(
                    layout=dict(
                        plot_bgcolor=app_color["graph_bg"],
                        paper_bgcolor=app_color["graph_bg"],
                    )
                ),
            ),
        ],
        id=f"graph-container-{mark}",
    )

    return o


def input_card(name, id="",N=1, type="number", **kwargs):
    assert isinstance(N,int) and N > 0, 'must have an inputs > 0'

    width = kwargs.pop('width','100%')
    height = kwargs.pop('height','200px')

    mark = id if id else name.lower().split("(")[0].strip().replace(" ", "-")
    inp = {"id": f"{mark}-input", "type": type, "style": {"width": width}}

    widget = dcc.Input
    if type == "number":
        widget = daq.Slider
        inp.pop("type")
        inp.pop("style")
    if type == "choice":
        widget = dcc.Slider
        inp.pop("type")
        inp.pop("style")        
        #inp["handleLabel"] = {"showCurrentValue": True, "label": "VALUE"}
    elif type == 'range':
        widget = dcc.RangeSlider

        inp = dict( marks=None,
                    tooltip={
                        "always_visible": True,
                        "template": "{value}%",
                        'placement':'left'
                    })


  
    if 'vertical' in kwargs:
        div = html.Div([
                widget(**inp, **kwargs),
                html.H6(name.upper(), className="graph__title",style={"width":f"{100./N}%",'padding-left':f"{5./(N)}%",'padding-right':f"{50./(N)}%",'margin-top':f"25%",'justify-content': 'left'}),
                ],
                style={"display": "table-cell","width":f"{100./N}%",'padding-left':f"{25./(N)}%",'padding-right':f"{50./(N)}%",'padding-top':f"10%",'padding-bottom':f"2%",'height':height,'justify-content': 'center'}
            ,) 
        
        return div
    else:
        div = html.Div(
            [
                html.Div(
                    [
                        html.Div(
                            html.H6(name.upper(), className="graph__title"),
                            style={"display": "table-cell", "float": "left"},
                        ),
                        html.Div(
                            widget(**inp, **kwargs),
                            style={
                                "display": "table-cell",
                                "width": width,
                                "float": "right",
                            },
                        ),
                    ],
                    style={
                        "display": "table-row",
                        "width": width,
                    },
                ),
            ],
            style={
                "display": "table",
                "width": width,
            },
            className="graph__container first",
        )
        return div


def readout_card(name, id=None, val=0.0):
    mark = name.lower().replace(" ",'-')

    if id is None:
        id=""

    div = html.Div(
        [
            html.Div(
                [
                    html.Div(
                        html.H6(name.upper(), className="graph__title"),
                        style={"display": "table-cell", "float": "left"},
                    ),
                    html.Div(
                        daq.LEDDisplay(
                            id=f"{mark}-display",
                            value=f"{val:3.6f}",
                            backgroundColor=app_color["graph_bg"],
                            size=25,
                            style={
                                "width": "100%",
                                "margin": "0px 0px 0px 0px",
                                "padding": "0px 0px 0px 0px",
                            },
                        ),
                        style={
                            "display": "table-cell",
                            # "width": "100%",
                            "float": "right",
                            "margin-right": "0px",
                        },
                    ),
                ],
                style={
                    "display": "table-row",
                    "width": "100%",
                },
            ),
        ],
        style={
            "display": "table",
            "width": "100%",
        },
        className="graph__container first",
    )
    return div