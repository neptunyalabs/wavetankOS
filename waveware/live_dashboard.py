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
log = logging.getLogger("dashboard")

POLL_INTERVAL = 1.0

external_stylesheets = ["https://codepen.io/chriddyp/pen/bWLwgP.css"]

app = dash.Dash(
    __name__,
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"}
    ],
    external_stylesheets=external_stylesheets,
)
app.title = TITLE = "WAVE TANK DASHBOARD"




# TODO: 1. Wave Measure Plot w/ act position and ultrasonic distance measurements
# TODO: 2. ref height / mode selection
# TODO: 3. pid control variables and cmd speed and feedback voltage
# TODO: 4. wave input config settings
# TODO: 5. add range limit slider for bounds



app.layout = html.Div(
    [
        # HEADER / Toolbar
        html.Div(
            [
                html.Div(
                    [
                        #html.H4(TITLE, className="app__header__title"),
                        html.Img(src='https://img1.wsimg.com/isteam/ip/3f70d281-e9f0-4171-94d1-bfd90bbedd4e/Neptunya_LogoTagline_Black_SolidColor_margin.png/:/cr=t:0%25,l:0%25,w:100%25,h:100%25/rs=h:150'),
                        html.P(
                            "This Dashboard Displays current values from the neptunya waveware system when turned on",
                            className="app__header__title--grey",
                        ),
                    ],
                    className="app__header__desc two-third column",
                ),
                html.Div(
                    [
                        html.Button(
                            "Calibrate".upper(),
                            id="calibrate-btn",
                            style=btn_header,
                        )
                    ]
                ),  
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
                html.Div([
                    html.H6("TEST NAME:",className="graph__title"),
                    html.Div([dcc.Input("Record Data With This Title", id="title-in", style={'width':'80%','padding-left':'1%','justify-content':'left'}),
                    html.Button("RUN",id='test-log-send',style={'background-color':'#FFFFFF','height':'40px','padding-top':'0%','padding-bottom':'5%','flex-grow': 1}) ],
                    style={'displaty':'flex'}),
                    dcc.RadioItems(
                            [mode_input_parms[k] for k in wave_drive_modes],
                            #[k for k in wave_drive_modes],
                            value=wave_drive_modes[0],
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
                            dcc.Textarea(id='test-log',value='',style={'width': '100%', 'height': 200}),
                            html.Button("record".upper(),id='test-log-send',style={'background-color':'#FFFFFF','height':'30px','padding-top':'0%','padding-bottom':'5%'})
                        ]
                    )]),
                    dcc.Tab(label='CONSOLE',children=[html.Div(
                        [
                            dcc.Textarea(id='console',value='',style={'width': '100%', 'height': 200}),
                            html.Button("record".upper(),id='test-log-send',style={'background-color':'#FFFFFF','height':'30px','padding-top':'0%','padding-bottom':'5%'})
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
                [
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



def main():
    """runs the dash / plotly process"""
    import os

    try:
        srv_host = '0.0.0.0' if ON_RASPI else '127.0.0.1'
        app.run_server(debug=not ON_RASPI,host=srv_host)

    except KeyboardInterrupt:
        sys.exit()


if __name__ == "__main__":


    main()























































#         html.Div(id='live-update-text'),
#         dcc.Graph(id='live-update-graph'), #TODO: define timeseries
#
#         #FOOTER
#         # dcc.Interval(
#         #     id='interval-component',
#         #     interval=1*1000, # in milliseconds
#         #     n_intervals=0
#         # )


# @app.callback(Output('live-update-text', 'children'),
#               Input('interval-component', 'n_intervals'))
# def update_metrics(n):
#     pass
#
#
# # Multiple components can update everytime interval gets fired.
# @app.callback(Output('live-update-graph', 'figure'),
#               Input('interval-component', 'n_intervals'))
# def update_graph_live(n):
#     pass


#
# dcc.Graph(
#     id="wind-direction",
#     figure=dict(
#         layout=dict(
#             plot_bgcolor=app_color["graph_bg"],
#             paper_bgcolor=app_color["graph_bg"],
#         )
#     ),
# ),

# dcc.Graph(
#     id="wind-histogram",
#     figure=dict(
#         layout=dict(
#             plot_bgcolor=app_color["graph_bg"],
#             paper_bgcolor=app_color["graph_bg"],
#         )
#     ),
# ),

# # pip install pyorbital
# from pyorbital.orbital import Orbital
# satellite = Orbital('TERRA')
#
# external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']
#
# app = dash.Dash(__name__, external_stylesheets=external_stylesheets)
# app.layout = html.Div(
#     html.Div([
#         html.H4('TERRA Satellite Live Feed'),
#         html.Div(id='live-update-text'),
#         dcc.Graph(id='live-update-graph'),
#         dcc.Interval(
#             id='interval-component',
#             interval=1*1000, # in milliseconds
#             n_intervals=0
#         )
#     ])
# )
#
#
# @app.callback(Output('live-update-text', 'children'),
#               Input('interval-component', 'n_intervals'))
# def update_metrics(n):
#     lon, lat, alt = satellite.get_lonlatalt(datetime.datetime.now())
#     style = {'padding': '5px', 'fontSize': '16px'}
#     return [
#         html.Span('Longitude: {0:.2f}'.format(lon), style=style),
#         html.Span('Latitude: {0:.2f}'.format(lat), style=style),
#         html.Span('Altitude: {0:0.2f}'.format(alt), style=style)
#     ]
#
#
# # Multiple components can update everytime interval gets fired.
# @app.callback(Output('live-update-graph', 'figure'),
#               Input('interval-component', 'n_intervals'))
# def update_graph_live(n):
#     satellite = Orbital('TERRA')
#     data = {
#         'time': [],
#         'Latitude': [],
#         'Longitude': [],
#         'Altitude': []
#     }
#
#     # Collect some data
#     for i in range(180):
#         time = datetime.datetime.now() - datetime.timedelta(seconds=i*20)
#         lon, lat, alt = satellite.get_lonlatalt(
#             time
#         )
#         data['Longitude'].append(lon)
#         data['Latitude'].append(lat)
#         data['Altitude'].append(alt)
#         data['time'].append(time)
#
#     # Create the graph with subplots
#     fig = plotly.tools.make_subplots(rows=2, cols=1, vertical_spacing=0.2)
#     fig['layout']['margin'] = {
#         'l': 30, 'r': 10, 'b': 30, 't': 10
#     }
#     fig['layout']['legend'] = {'x': 0, 'y': 1, 'xanchor': 'left'}
#
#     fig.append_trace({
#         'x': data['time'],
#         'y': data['Altitude'],
#         'name': 'Altitude',
#         'mode': 'lines+markers',
#         'type': 'scatter'
#     }, 1, 1)
#     fig.append_trace({
#         'x': data['Longitude'],
#         'y': data['Latitude'],
#         'text': data['time'],
#         'name': 'Longitude vs Latitude',
#         'mode': 'lines+markers',
#         'type': 'scatter'
#     }, 2, 1)
#
#     return fig
