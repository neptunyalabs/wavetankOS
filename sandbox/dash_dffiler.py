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
        dcc.Tab(label='Scatter Plot', style={'backgroundColor': '#0074D9', 'color': '#ffffff'}, selected_style={'backgroundColor': '#0074D9', 
'color': '#ffffff'}, children=[
            html.Div([
                html.Div([
                    dcc.Dropdown(id='run-id-dropdown', multi=True, placeholder='Select run_id(s)', style={'backgroundColor': '#0074D9', 'color': 
'#001f3f'}),
                    dcc.RangeSlider(id='hs-range-slider', min=0, max=10, step=0.1, marks={i: str(i) for i in range(11)}, value=[0, 10], 
tooltip={"placement": "bottom", "always_visible": True}, updatemode='drag'),
                    html.Div(id='hs-range-slider-output', style={'margin-top': 20}),
                    dcc.RangeSlider(id='ts-range-slider', min=0, max=10, step=0.1, marks={i: str(i) for i in range(11)}, value=[0, 10], 
tooltip={"placement": "bottom", "always_visible": True}, updatemode='drag'),
                    html.Div(id='ts-range-slider-output', style={'margin-top': 20}),
                    dcc.Input(id='run-title-input', type='text', placeholder='Filter by run_title', style={'backgroundColor': '#0074D9', 
'color': '#001f3f'}),
                ], style={'width': '25%', 'display': 'inline-block', 'vertical-align': 'top', 'padding': '20px'}),
                html.Div([
                    dcc.Graph(id='scatter-plot', style={'height': '100vh'})
                ], style={'width': '75%', 'display': 'inline-block', 'padding': '20px'})
            ])
        ])
    ]),
    dcc.Interval(id='interval-component', interval=60*1000, n_intervals=0)  # Fetch data every minute
])

# Function to fetch data from the endpoint
def fetch_data():
    response = requests.get('http://localhost:8777/run_summary')
    if response.status_code == 200:
        data = response.json()
        df = pd.DataFrame.from_dict(data, orient='index')
        df.reset_index(inplace=True)
        df.rename(columns={'index': 'run_id'}, inplace=True)
        return df
    else:
        return pd.DataFrame(columns=['Hs', 'Ts', 'run_id', 'run_title'])

# Callback to update the data
@app.callback(
    [Output('data-table', 'data'),
     Output('run-id-dropdown', 'options')],
    [Input('interval-component', 'n_intervals')]
)
def update_data(n_intervals):
    df = fetch_data()
    data = df.to_dict('records')
    dropdown_options = [{'label': str(run_id), 'value': run_id} for run_id in df['run_id'].unique()]
    return data, dropdown_options

# Callback to update the scatter plot based on filters
@app.callback(
    Output('scatter-plot', 'figure'),
    [Input('run-id-dropdown', 'value'),
     Input('hs-range-slider', 'value'),
     Input('ts-range-slider', 'value'),
     Input('run-title-input', 'value')],
    [State('data-table', 'data')]
)
def update_scatter_plot(selected_run_ids, hs_range, ts_range, title_filter, data):
    if not data:
        raise PreventUpdate
    
    df = pd.DataFrame(data)
    
    if selected_run_ids:
        df = df[df['run_id'].isin(selected_run_ids)]
    if hs_range:
        df = df[(df['Hs'] >= hs_range[0]) & (df['Hs'] <= hs_range[1])]
    if ts_range:
        df = df[(df['Ts'] >= ts_range[0]) & (df['Ts'] <= ts_range[1])]
    if title_filter:
        df = df[df['run_title'].str.contains(title_filter, case=False, na=False)]
    
    fig = px.scatter(df, x='Hs', y='Ts', color='run_id', title='Scatter Plot of Hs vs Ts', color_continuous_scale=px.colors.sequential.Blues)
    fig.update_layout(
        plot_bgcolor='#001f3f',
        paper_bgcolor='#001f3f',
        font_color='#ffffff',
        legend=dict(
            bgcolor='#001f3f',
            font=dict(color='#ffffff')
        ),
        xaxis=dict(tickfont=dict(color='#ffffff')),
        yaxis=dict(tickfont=dict(color='#ffffff'))
    )
    return fig

# Run the app
if __name__ == '__main__':
    app.run_server(debug=True,host="127.0.0.1")

