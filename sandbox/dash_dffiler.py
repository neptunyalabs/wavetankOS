# app.py

import dash
from dash import dcc, html, Input, Output, State
import dash_table
import pandas as pd
import requests
import plotly.express as px
from dash.exceptions import PreventUpdate

# Initialize the Dash app
app = dash.Dash(__name__)
app.title = "Run Summary Dashboard"

x_parm_options = [{'label'}]

# Define the layout with a blue and white color scheme
app.layout = html.Div(style={'backgroundColor': '#001f3f', 'color': '#ffffff', 'height': '100vh'}, children=[
    dcc.Tabs(id="tabs", children=[
        dcc.Tab(label='Table', style={'backgroundColor': '#0074D9', 'color': '#ffffff'}, selected_style={'backgroundColor': '#0074D9', 'color': 
'#ffffff'}, children=[
            html.Div(id='table-div', children=[
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
            ])
        ]),
        dcc.Tab(label='Scatter Plot', style={'backgroundColor': '#0074D9', 'color': '#999999'}, selected_style={'backgroundColor': '#0074D9', 
'color': '#000000'}, children=[
            html.Div([
                html.Div([
                    dcc.Dropdown(id='x-parm-id',value='Hf',style={'backgroundColor': '#0074D9', 'color': '#000000'}),
                    dcc.Dropdown(id='y-parm-id',value='Ts',style={'backgroundColor': '#0074D9', 'color': '#000000'}),     
                    html.H6('Hs Selection'),          
                    dcc.RangeSlider(id='hs-range-slider', min=0, max=3, value=[0, 10], tooltip={"placement": "bottom", "always_visible": True}, updatemode='drag'),
                    html.H6('Ts Selection'),
                    dcc.RangeSlider(id='ts-range-slider', min=0, max=3, value=[0, 10], tooltip={"placement": "bottom", "always_visible": True}, updatemode='drag'),
                    html.H6('Filter Titles'),
                    dcc.Input(id='run-title-input', type='text', placeholder='Filter by run_title'),
                ], style={'width': '25%', 'display': 'inline-block', 'vertical-align': 'top', 'padding': '20px'}),
                html.Div([
                    dcc.Graph(id='scatter-plot', style={'height': '100vh'})
                ], style={'width': '70%', 'display': 'inline-block'})
            ])
        ])
    ]),
    dcc.Interval(id='interval-component', interval=60*1000, n_intervals=0)  # Fetch data every minute
])


example_data = [
    {'run_id':0,'Hs':0.1,'Ts':0.1,'Hf':0.0, 'run_title':'H=0.1'},
    {'run_id':1,'Hs':0.1,'Ts':0.2,'Hf':0.2, 'run_title':'H=0.1'},
    {'run_id':2,'Hs':0.1,'Ts':0.4,'Hf':0.4, 'run_title':'H=0.1'},
    {'run_id':3,'Hs':0.1,'Ts':0.8,'Hf':0.8, 'run_title':'H=0.1'},
    {'run_id':4,'Hs':0.1,'Ts':1.2,'Hf':0.6, 'run_title':'H=0.1'},
    {'run_id':5,'Hs':0.1,'Ts':1.5,'Hf':0.5, 'run_title':'H=0.1'},
    {'run_id':6,'Hs':0.1,'Ts':2.0,'Hf':0.4, 'run_title':'H=0.1'},
    {'run_id':7,'Hs':0.1,'Ts':2.5,'Hf':0.35,'run_title':'H=0.1'},
    {'run_id':8, 'Hs':0.2,'Ts':0.1,'Hf':0.3, 'run_title':'H=0.2'},
    {'run_id':9, 'Hs':0.2,'Ts':0.2,'Hf':0.4, 'run_title':'H=0.2'},
    {'run_id':10,'Hs':0.2,'Ts':0.4,'Hf':0.5, 'run_title':'H=0.2'},
    {'run_id':11,'Hs':0.2,'Ts':0.8,'Hf':0.7, 'run_title':'H=0.2'},
    {'run_id':12,'Hs':0.2,'Ts':1.2,'Hf':0.6, 'run_title':'H=0.2'},
    {'run_id':13,'Hs':0.2,'Ts':1.5,'Hf':0.55, 'run_title':'H=0.2'},
    {'run_id':14,'Hs':0.2,'Ts':2.0,'Hf':0.45, 'run_title':'H=0.2'},
    {'run_id':15,'Hs':0.2,'Ts':2.5,'Hf':0.4 ,'run_title':'H=0.2'},    
]

# Function to fetch data from the endpoint
def fetch_data():
    # response = requests.get('http://localhost:8777/run_summary')
    # if response.status_code == 200:
    #     data = response.json()
    #     df = pd.DataFrame.from_dict(data, orient='index')
    #     df.reset_index(inplace=True)
    #     df.rename(columns={'index': 'run_id'}, inplace=True)
    #     return df
    # else:
    #return pd.DataFrame(columns=['Hs', 'Ts', 'run_id', 'run_title'])
    df = pd.DataFrame(data=example_data)
    df.reset_index(inplace=True)
    #df.rename(columns={'index': 'run_id'}, inplace=True)
    return df

# Callback to update the data
@app.callback(
    [Output('data-table', 'data'),
     Output('x-parm-id', 'options'),
     Output('y-parm-id', 'options')],
    [Input('interval-component', 'n_intervals')]
)
def update_data(n_intervals):
    df = fetch_data()
    data = df.to_dict('records')
    runs = pd.unique(df['run_title'])
    dropdown_options = [{'label': str(run_id), 'value': run_id} 
                                  for run_id in runs]
    #dropdown_options,
    return data,  df.columns,df.columns

# Callback to update the scatter plot based on filters
@app.callback(
    Output('scatter-plot', 'figure'),
    [Input('hs-range-slider', 'value'),
     Input('ts-range-slider', 'value'),
     Input('run-title-input', 'value'),
     Input('x-parm-id', 'value'),
     Input('y-parm-id', 'value')],     
    [State('data-table', 'data')]
)
def update_scatter_plot( hs_range, ts_range, title_filter,xparm,yparm, data):
    if not data:
        raise PreventUpdate
    
    df = pd.DataFrame(data)
    if hs_range:
        df = df[(df['Hs'] >= hs_range[0]) & (df['Hs'] <= hs_range[1])]
    if ts_range:
        df = df[(df['Ts'] >= ts_range[0]) & (df['Ts'] <= ts_range[1])]
    if title_filter:
        df = df[df['run_title'].str.contains(title_filter, case=False, na=False)]

    fig = px.line(df, x=xparm, y=yparm, color='run_title', title=f'Scatter Plot of {xparm} vs {yparm}')
    fig.update_layout(
        plot_bgcolor='#001f3f',
        paper_bgcolor='#001f3f',
        font_color='#ffffff',
        legend=dict(
            bgcolor='#001f3f',
            font=dict(color='#ffffff')
        ),
        xaxis=dict(tickfont=dict(color='#ffffff')),
        yaxis=dict(tickfont=dict(color='#ffffff')),
        
    )
    return fig

# Run the app
if __name__ == '__main__':
    app.run_server(debug=True,host="127.0.0.1")

