# from piplates import DACC

import datetime

import dash
from dash import dcc, html, dash_table
import dash_daq as daq

from waveware.config import *
from waveware.data import *
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
                            min=editable_parmaters['wave-ts'][-2],
                            max=editable_parmaters['wave-ts'][-1],
                            value=editable_parmaters['wave-ts'][-1],
                            vertical=True,
                            N=Ninputs
                        ),
                    'wave-hs':dict(
                            name="Hs".upper(),
                            id="wave-hs",
                            type="number",
                            min=editable_parmaters['wave-hs'][-2],
                            max=editable_parmaters['wave-hs'][-1],
                            value=editable_parmaters['wave-hs'][-2],
                            marks=None,
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

def generate_plot(title, id=None,add_to_plots=True,**kwargs):

    mark = id if id else title.lower().split("(")[0].strip().replace(" ", "-")
    if add_to_plots: 
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
                **kwargs
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
                    allowCross=False,
                    tooltip={
                        "always_visible": True,
                        "template": "{value}%",
                        'placement':'left'
                    },
                    #style={'padding': '0px 0px 0px 25px'}, #doesn't work
                    id=inp['id'],

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


def readout_card(name, id=None, val=0.0,mark=None):
    
    if mark is None:
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
                    html.Div([
                    dcc.Input("Record Data With This Title", id="title-in", style={'width':'75%','padding-right':'1%','justify-content':'left'}),
                    html.Button("GET",id='drive-refresh',style={'background-color':'#33CAFF','height':'38px','width':"12%",'padding-top':'0%','padding-bottom':'5%','flex-grow': 1,'justify-content':'left'}),
                    html.Button("SET",id='drive-set-exec',style={'background-color':'#59F','height':'38px','width':"12%",'padding-top':'0%','padding-bottom':'5%','flex-grow': 1,'justify-content':'left'})
                    ],style={'display':'flex'}),
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
                    dcc.Tab(label='LOG',children=[html.Div(
                        [
                            dcc.Textarea(id='console',value='',readOnly=True,style={'width': '100%', 'height': "100%"}),
                        ]
                    )]),                    
                    dcc.Tab(label='EDIT',children=[html.Div([
                                dash_table.DataTable(  data=[{'key':k,'val':v} for k,v in table_parms.items()],
                                columns=[{'id':'key','name':'Parm','deletable': False,'renamable': False,'editable': False},
                                         {'id':'val','name':'Val','deletable': False,'renamable': False,'editable': True}],
                                page_action='none',
                                id='edit-control-table',
                                style_table={'height': '100%', 'overflowY': 'auto','width':'100%'},
                                editable=True,#DEBUG, #FIXME: prod make this a special features, hide table as well
                                style_cell={
                                    # 'padding': '5px'
                                    'backgroundColor': 'white',
                                    'color': triton_bk,
                                    'textAlign': 'left',
                                },
                                style_header={
                                    'backgroundColor': 'white',
                                    'color': triton_bk,
                                    'fontWeight': 'bold'
                                },
                                css=[
                                    {"selector": ".dash-spreadsheet-container table", "rule": '--text-color: black !important'},
                                ],
                                style_data_conditional=[
                                    {
                                        "if": {"state": "active"},  # 'active' | 'selected'
                                        "backgroundColor": nept_bk2,
                                        "border": "3px solid white",
                                        "color": triton_bk,
                                    },{
                                        "if": {"state": "selected"},
                                        # "backgroundColor": "rgba(255,255,255, 0.1)",
                                        "backgroundColor": "white",
                                    },
                                ],),
                        html.Button("save".upper(),id='cntl-vals-save',style={'background-color':'#FFFFFF','height':'30px','padding-top':'0%','padding-bottom':'5%'})                                
                        ]
                    )]),                     
                    dcc.Tab(label='NOTE',children=[html.Div(
                        [
                            dcc.Textarea(id='test-log',value='',style={'width': '100%', 'height': "100%"}),
                            html.Button("record".upper(),id='test-log-send',style={'background-color':'#FFFFFF','height':'30px','padding-top':'0%','padding-bottom':'5%'})
                        ]
                    )]),                                
                ],style={'height':'100%','overflowY': 'auto'}),
                html.Div(
                    [
                    # Station 1
                    html.H6("Wave Gen Control:".upper(),className="graph__title"),

                    readout_card("fb volts",mark='wave_fb_volt'),
                    readout_card("act pct",mark="wave_fb_pct"),
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
            ],
            className=" column histogram__direction",
            style={'width':'25%'}
            ),
            # PLOTS
            dcc.Tabs(id='main-tabs',children=
            [
                dcc.Tab(label='Live Data',
                        style = {'width':'49%','background-color':'#001f3f','color':'#FFFFFF'},
                        selected_style={'background-color':'#59F'},
                        children=[
                html.Div(
                [   #html.H6("",id="current-title",className="graph__title"),
                    generate_plot("Act Position (m)".upper()),
                    generate_plot("Act Velocity (m/s)".upper()),
                    generate_plot("Encoder Z 1-4 (mm)".upper()),
                    generate_plot("Echo Height (mm)".upper()), #TODO: wave plot
                    #TODO: test set overview
                    
                ],className="column wind__speed__container"),
                ],className="column wind__speed__container"),
                dcc.Tab(label='Test Summary',
                        style = {'width':'49%','background-color':'#001f3f','color':'#FFFFFF'},
                        selected_style={'background-color':'#59F'},
                        children=[
                html.Div([
                html.Div([
                html.Div([
                    dcc.Dropdown(id='x-parm-id',value='Hf',style={'backgroundColor': '#001f3f', 'color': '#000000'}),
                    dcc.Dropdown(id='y-parm-id',value='Ts',style={'backgroundColor': '#001f3f', 'color': '#000000'}),     
                    html.H6('Hs Selection',style={'color':'#FFFFFF'}),          
                    dcc.RangeSlider(id='hs-range-slider', min=0, max=3, value=[0, 10], tooltip={"placement": "bottom", "always_visible": True}, updatemode='drag'),
                    html.H6('Ts Selection',style={'color':'#FFFFFF'}),
                    dcc.RangeSlider(id='ts-range-slider', min=0, max=3, value=[0, 10], tooltip={"placement": "bottom", "always_visible": True}, updatemode='drag'),
                    html.H6('Filter Titles',style={'color':'#FFFFFF'}),
                    dcc.Input(id='run-title-input', type='text', placeholder='Filter by run_title'),
                ], style={'width': '25%', 'display': 'inline-block', 'vertical-align': 'top', 'padding': '20px'}),
                html.Div([
                    #dcc.Graph(id='scatter-plot', style={'height': '100vh'})
                    generate_plot('results-plot', style={'height': '75vh','width':'100%'},add_to_plots=False)
                ], style={'width': '70%', 'display': 'inline-block'})
                ]),
                html.Div(id='table-div', children=[
                html.H6('Test Data',style={'color':'#FFFFFF'}),
                dash_table.DataTable(
                    id='data-table',
                    columns=[
                        {'name': 'Hs', 'id': 'Hs', 'type': 'numeric'},
                        {'name': 'Ts', 'id': 'Ts', 'type': 'numeric'},
                        {'name': 'Hf', 'id': 'Hf', 'type': 'numeric'},
                        {'name': 'run_id', 'id': 'run_id', 'type': 'numeric'},
                        {'name': 'run_title', 'id': 'run_title', 'type': 'text'}
                    ],
                    data=[],
                    page_size=10,
                    style_header={'backgroundColor': '#0074D9', 'color': '#ffffff'},
                    style_cell={'backgroundColor': '#001f3f', 'color': '#ffffff'}
                )
                ]),
                ])
            ]),
            ],content_style={'width':'100%'},
              style={'width':'100%','height':'50px'},
              parent_style={'width':'100%','margin-left':'20px'})
                
        ], className="app__content body",),
    dcc.Interval(
    id=f"graph-update",
    interval=1000*graph_update_interval,
    n_intervals=0,
    ),
    dcc.Interval(
    id=f"num-raw-update",
    interval=1000*num_update_interval,
    n_intervals=0,
    ),    
    html.Div(id="hidden-div", style={"display":"none"})
    ],className="app__container body")
