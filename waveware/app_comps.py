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


mode_input_parms = dict(
                         stop=   {
                                    "label": html.Div(['STOP'], style={'color': 'WHITE', 'font-size': 20}),
                                    "value": "STOP",
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
                    'z-ref':dict(
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
                    'z-range':dict(
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
                    'trq-lim':dict(
                        name="Torque".upper(),
                        id="trq-lim",
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
    inp = {"id": f"{mark.replace('_','-')}-input", "type": type, "style": {"width": width}}

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
                    },
                    id=inp['id']
                    )


  
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



DASH_LAY = html.Div(
    [
        # HEADER / Toolbar
        html.Div(
            [
                html.Div(
                    [   
                    #html.H4(TITLE, className="app__header__title"),
                    #DASH served from assets folder
                    html.Img(src='assets/Neptunya_LogoTagline_White_SolidColor.png',style={'width':'66%'}),
                    html.P(
                        "Turn on Data Aquisition (DAC) to record data to S3.",
                        className="app__header__title--grey",
                    ),
                    html.P("Enable Wave Motor before setting the Run Mode.",
                        className="app__header__title--grey",
                    ),
                    html.P("Always keep your hands away from the wave drive or any other pinch points while the motor is enabled and powered on",
                        className="app__header__title--grey",
                    ),
                    ],
                    className="app__header__desc two-third column",
                ),
                # html.Div( #TODO: interactive calibration, for now use mpu
                #     [
                #         html.Button(
                #             "Calibrate".upper(),
                #             id="calibrate-btn",
                #             style=btn_header,
                #         )
                #     ]
                # ),  
                html.Div(
                    [
                        html.Button(
                            "Zero".upper(),
                            id="zero-btn",
                            style=btn_header,
                        )
                    ]
                ),
                html.Div(
                    [
                        # html.H6(
                        #     
                        #     id="daq_msg",
                        #     style={"text-align": "center"},
                        # ),
                        daq.BooleanSwitch(label="DAC ON/OFF",on=False, id="daq_on_off"),
                    ],
                    className="column",
                ),                
                html.Div([daq.StopButton(id="stop-btn", buttonText="STOP")]),                
                html.Div(
                    [
                        daq.PowerButton(label="WAVE ON/OFF",on=False, id="motor_on_off"),
                    ],
                    className="one-third column",
                ),         
            ],
            className="app__header",
        ),
        # BODY
        html.Div([
            # READOUTS
            html.Div([
                html.H6("DRIVE CONFIG:",className="graph__title"),
                html.Div([
                    html.Div([dcc.Input("Record Data With This Title", id="title-in", style={'width':'80%','padding-left':'1%','justify-content':'left'}),
                    html.Button("RUN",id='drive-set-exec',style={'background-color':'#FFFFFF','height':'40px','padding-top':'0%','padding-bottom':'5%','flex-grow': 1}) ],
                    style={'displaty':'flex'}),
                    dcc.RadioItems(
                            [mode_input_parms[k] for k in wave_drive_modes],
                            #[k for k in wave_drive_modes],
                            value=wave_drive_modes[0].upper(),
                            id='mode-select',
                            inline=True,
                            inputStyle = {'width':f'{(80)/M}%', 'padding':'0 3% 3% 0'},
                            labelStyle={'width':f'{(80)/M}%','padding':'0 3% 3% 0'},
                            style={'width':'100%','background':triton_bk,'display':'inline-block'}
                        ),
                    html.Div([
                        html.Div([
                                input_card(**wave_input_parms[k]) for k in wave_inputs if k in wave_input_parms
                                ])
                        ],
                        style={
                        "display": "table-row",
                        "width": "100%",
                        "justify-content":"center"
                        })
                    ],
                    style={
                        "display": "table",
                        "width": "100%",
                        "height": "250px",
                    },
                    className="graph__container first",
                ),

                # Write Test Log
                dcc.Tabs([
                    dcc.Tab(label='TEST LOG',children=[html.Div(
                        [
                            dcc.Textarea(id='test-log',value='',style={'width': '100%', 'height': "20%"}),
                            html.Button("record".upper(),id='test-log-send',style={'background-color':'#FFFFFF','height':'30px','padding-top':'0%','padding-bottom':'5%'})
                        ]
                    )]),
                    dcc.Tab(label='CONSOLE',children=[html.Div(
                        [
                            dcc.Textarea(id='console',value='',style={'width': '100%', 'height': "20%"}),
                        ]
                    )]),                                 
                ]),
                html.Div(
                    [
                    # Station 1
                    html.H6("Wave Gen Control:".upper(),className="graph__title"),
                    readout_card("z_cur"),
                    readout_card("z_cmd"),
                    readout_card("z_wave"),
                    readout_card("v_cur"),
                    readout_card("v_cmd"),
                    readout_card("v_wave"),                        
                    
                    html.H6("Encoder Z 1-4:".upper(),className="graph__title"),
                    readout_card("z1"),
                    readout_card("z2"),
                    readout_card("z3"),
                    readout_card("z4"),

                    html.H6("Echo Sensor Z 1-4:".upper(),className="graph__title"),
                    readout_card("e1"),
                    readout_card("e2"),
                    readout_card("e3"),
                    readout_card("e4"),
                    ]
                ),

                html.Div(
                    [
                    html.H6("Read / Edit Values:".upper(),className="edit_title",style={'display':'none'}), dash_table.DataTable(  data=[],
                                columns=[],
                                page_action='none',
                                style_table={'height': '100px', 'overflowY': 'auto','width':'90%'})
                ])               
            ],
            className=" column histogram__direction",
            style={'width':'25%'}
            ),
            # PLOTS
            html.Div(
                [   html.H6("",id="current-title",className="graph__title"),
                    generate_plot("Encoder Z 1-4 (mm)".upper()),
                    generate_plot("Echo Height (mm)".upper()), #TODO: wave plot
                    generate_plot("Wave Generator (m),(m/s)".upper()),
                    #TODO: test set overview
                    
                ],
                className="two-thirds column wind__speed__container",
            ),
        ],
        className="app__content body",
    ),
    dcc.Interval(
    id=f"graph-update",
    interval=2.5*1000,
    n_intervals=0,
    ),
    dcc.Interval(
    id=f"num-raw-update",
    interval=1*500.,
    n_intervals=0,
    ),    
    html.Div(id="hidden-div", style={"display":"none"})
    ],
    className="app__container body",
)
