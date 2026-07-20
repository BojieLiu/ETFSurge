import * as echarts from 'echarts/core'
import { CandlestickChart, BarChart, LineChart } from 'echarts/charts'
import { GridComponent, DataZoomComponent, LegendComponent, TooltipComponent, AxisPointerComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  CandlestickChart, BarChart, LineChart,
  GridComponent, DataZoomComponent, LegendComponent, TooltipComponent, AxisPointerComponent,
  CanvasRenderer,
])

export default echarts
