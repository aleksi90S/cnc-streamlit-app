import streamlit as st
import pandas as pd
import numpy as np
import io
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from openpyxl import Workbook
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.utils.dataframe import dataframe_to_rows

# --- Page Setup ---
st.set_page_config(page_title="CnC Tool", layout="centered")

# --- Login Authentication ---
def check_password():
    def password_entered():
        if (st.session_state["username"] == st.secrets["auth"]["username"] and
            st.session_state["password"] == st.secrets["auth"]["password"]):
            st.session_state["authenticated"] = True
        else:
            st.session_state["authenticated"] = False
            st.error("❌ Incorrect username or password")

    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if not st.session_state["authenticated"]:
        with st.form("Login"):
            st.text_input("Username", key="username")
            st.text_input("Password", type="password", key="password")
            submitted = st.form_submit_button("🔐 Login")
            if submitted:
                password_entered()
        return False
    else:
        return True

# --- MAIN APP ---
if check_password():

    # --- Load Data ---
    @st.cache_data
    def load_data():
        orders_path = st.secrets["files"]["orders_path"]
        calendar_path = st.secrets["files"]["calendar_path"]

        df_orders = pd.read_json(orders_path, lines=True, convert_dates=['transaction_date'])
        df_orders = df_orders[df_orders['created_sales_net_amount_euro'] > 0]
        df_calendar = pd.read_json(calendar_path, lines=True, convert_dates=['day_date'])
        df_calendar = df_calendar[['day_date', 'fiscal_month_no', 'iso_month_name_long', 'fiscal_year_label']]
        df = pd.merge(df_orders, df_calendar, left_on='transaction_date', right_on='day_date')
        df.drop(columns=['day_date'], inplace=True)
        return df

    df = load_data()

    # --- Page Selector ---
    page = st.sidebar.selectbox("📂 Select a Page", ["Summary Dashboard", "Pricing Impact Analysis"])

    # --- PAGE 1: SUMMARY ---
    if page == "Summary Dashboard":
        st.title("📦 Click & Collect Summary")
        st.markdown("Use the filters below and click **Submit** to run the summary.")
        total_orders = len(df)
        formatted_total_orders = f"{total_orders:,}".replace(",", " ")
        st.markdown(f"**🧾 Total Orders in Dataset:** {formatted_total_orders}")

        with st.form("filter_form"):
            column = st.selectbox("🔍 Select a column to filter:", df[['created_sales_net_amount_euro', 'item_vat_amount', 'created_net_quantity', 'orderlines']].columns)
            if np.issubdtype(df[column].dtype, np.number):
                col1, col2 = st.columns(2)
                min_val = float(df[column].min())
                max_val = float(df[column].max())
                input_min = col1.number_input("🔢 Min value", value=min_val)
                input_max = col2.number_input("🔢 Max value", value=max_val)
            elif np.issubdtype(df[column].dtype, np.datetime64):
                min_val = df[column].min().date()
                max_val = df[column].max().date()
                input_min, input_max = st.date_input("📅 Select date range:", value=(min_val, max_val), min_value=min_val, max_value=max_val)
            else:
                st.warning("⚠️ Column must be numeric or datetime.")
                st.stop()

            fiscal_years = st.multiselect(
                "📆 Select fiscal years:",
                sorted(df['fiscal_year_label'].dropna().unique()),
                default=sorted(df['fiscal_year_label'].dropna().unique())
            )

            submitted = st.form_submit_button("✅ Submit")

        def filter_and_summarize(df, column, min_value, max_value, fiscal_years):
            if np.issubdtype(df[column].dtype, np.datetime64):
                min_value = pd.to_datetime(min_value)
                max_value = pd.to_datetime(max_value)
            filtered_df = df[(df[column] >= min_value) & (df[column] <= max_value) & (df['fiscal_year_label'].isin(fiscal_years))]
            orders = len(filtered_df)
            summary = filtered_df.agg({
                'created_sales_net_amount_euro': ['mean', 'median', 'min', 'max', lambda x: x.quantile(0.25), lambda x: x.quantile(0.75)],
                'created_net_quantity': ['mean', 'median', 'min', 'max', lambda x: x.quantile(0.25), lambda x: x.quantile(0.75)],
                'orderlines': ['mean', 'median', 'min', 'max', lambda x: x.quantile(0.25), lambda x: x.quantile(0.75)]
            })
            summary.rename(index={'<lambda_0>': '25th Percentile', '<lambda_1>': '75th Percentile'}, inplace=True)
            summary_df = summary.T
            summary_df.columns = ['Mean', 'Median', 'Min', 'Max', '25th Percentile', '75th Percentile']
            summary_df = summary_df[['Mean', '25th Percentile', 'Median', '75th Percentile', 'Min', 'Max']]
            summary_df.index.name = 'Metric'
            return summary_df, orders, filtered_df

        if submitted:
            try:
                summary_df, order_count, filtered_df = filter_and_summarize(df, column, input_min, input_max, fiscal_years)
                formatted_order_count = f"{order_count:,}".replace(",", " ")
                st.markdown(f"### 📄 Summary Table (Selected Orders: {formatted_order_count})")
                st.dataframe(summary_df.style.format("{:.2f}"))

                # Excel export
                output = io.BytesIO()
                wb = Workbook()
                ws = wb.active
                ws.title = "Filtered Orders"
                for row in dataframe_to_rows(filtered_df, index=False, header=True):
                    ws.append(row)
                last_col = chr(64 + filtered_df.shape[1]) if filtered_df.shape[1] <= 26 else 'Z'
                table = Table(displayName="FilteredOrdersTable", ref=f"A1:{last_col}{len(filtered_df)+1}")
                style = TableStyleInfo(name="TableStyleMedium9", showRowStripes=True)
                table.tableStyleInfo = style
                ws.add_table(table)
                wb.save(output)
                output.seek(0)

                st.download_button(
                    label="⬇️ Download Filtered Data as Excel",
                    data=output,
                    file_name="filtered_orders.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            except Exception as e:
                st.error(f"❌ Error:\n\n{e}")

    # --- PAGE 2: PRICING IMPACT ---
    elif page == "Pricing Impact Analysis":
        st.title("💰 Pricing Threshold Impact Analysis")
        with st.form("pricing_form"):
            column = st.selectbox("📈 Revenue Column", df[['created_sales_net_amount_euro', 'item_vat_amount', 'created_net_quantity', 'orderlines']].columns)
            threshold_price = st.number_input("💸 Threshold Price (e.g., new service fee)", value=2.0, step=0.5)
            threshold_value = st.number_input("📊 Apply to orders ≤ this value:", value=20.0, step=1.0)
            drop_off_rate = st.slider("📉 Estimated Drop-off Rate (%)", 0.0, 1.0, 0.1, step=0.01)
            fiscal_years = st.multiselect(
                "📆 Fiscal years to include:",
                sorted(df['fiscal_year_label'].dropna().unique()),
                default=sorted(df['fiscal_year_label'].dropna().unique())
            )
            pricing_submit = st.form_submit_button("✅ Run Pricing Impact Analysis")

        def analyze_pricing_impact(df, column, threshold_price, threshold_value, drop_off_rate, fiscal_years):
            df = df[df['fiscal_year_label'].isin(fiscal_years)]
            total_orders = len(df)
            total_revenue = df[column].sum()

            impacted_orders = df[df[column] <= threshold_value].copy()
            impacted_order_count = len(impacted_orders)
            lost_orders_count = int(impacted_order_count * drop_off_rate)
            lost_orders = impacted_orders.sample(n=lost_orders_count, random_state=42)
            revenue_lost = lost_orders[column].sum()
            revenue_gained = (impacted_order_count - lost_orders_count) * threshold_price
            net_revenue_impact = revenue_gained - revenue_lost

            def fmt_pct(x): return f"{x * 100:.1f}".replace(".", ",") + "%"

            summary = pd.DataFrame({
                'Metric': ['Impacted Orders', 'Revenue Gained', 'Lost Orders', 'Revenue Lost', 'Net Revenue Impact'],
                'Absolute Value': [impacted_order_count, revenue_gained, lost_orders_count, round(revenue_lost, 1), round(net_revenue_impact, 1)],
                'Relative Share': [
                    fmt_pct(impacted_order_count / total_orders) if total_orders else "0,0%",
                    fmt_pct(revenue_gained / total_revenue) if total_revenue else "0,0%",
                    fmt_pct(lost_orders_count / total_orders) if total_orders else "0,0%",
                    fmt_pct(revenue_lost / total_revenue) if total_revenue else "0,0%",
                    fmt_pct(net_revenue_impact / total_revenue) if total_revenue else "0,0%",
                ]
            })

            # Visualization: Orders Breakdown
            kept_orders_count = impacted_order_count - lost_orders_count
            unimpacted_orders_count = total_orders - impacted_order_count
            segments = [unimpacted_orders_count, kept_orders_count, lost_orders_count]
            labels = ["Unimpacted", "Kept", "Lost"]
            colors = ["#1f77b4", "#2ca02c", "#ff7f0e"]
            pct = [count / total_orders if total_orders else 0 for count in segments]

            fig1, ax1 = plt.subplots(figsize=(6, 5))
            cumulative = 0
            for val, label, color, p in zip(segments, labels, colors, pct):
                ax1.bar("All CnC Orders", val, bottom=cumulative, label=label, color=color)
                if val > 0:
                    ax1.text(0, cumulative + val / 2,
                             f"{label}: {val:,}".replace(",", " ") + f" ({p * 100:.1f}%)".replace(".", ","),
                             ha='center', va='center', fontsize=10,
                             bbox=dict(facecolor=color, alpha=0.6, edgecolor='black', boxstyle='round,pad=0.4'),
                             color='white' if label != "Unimpacted" else 'black')
                cumulative += val
            ax1.set_title("CnC Orders Breakdown")
            ax1.set_ylabel("Number of Orders")
            ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{int(x):,}".replace(",", " ")))
            fig1.tight_layout()

            # Visualization: Revenue Impact
            categories = ['Revenue Lost', 'Revenue Gained', 'Net Impact']
            values = [-revenue_lost, revenue_gained, net_revenue_impact]
            colors = ['red', 'green', 'blue']
            abs_max = max(abs(val) for val in values)
            buffer = abs_max * 0.15
            fig2, ax2 = plt.subplots(figsize=(8, 4))
            bars = ax2.barh(categories, values, color=colors)
            ax2.axvline(0, color='black', linewidth=0.8)
            ax2.set_xlim(-abs_max - buffer, abs_max + buffer)
            ax2.set_title("Revenue Impact Overview")
            ax2.set_xlabel("Euros (€)")
            ax2.xaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"{int(x):,} €".replace(",", " ")))

            for bar in bars:
                width = bar.get_width()
                label = f"{abs(width):,.0f} €".replace(",", " ")
                y_pos = bar.get_y() + bar.get_height() / 2
                label_offset = 0.05 * abs_max
                ax2.text(width + label_offset if width > 0 else width - label_offset, y_pos,
                         label, va='center', ha='left' if width > 0 else 'right',
                         fontsize=9, color='white' if abs(width) > 0.1 * abs_max else 'black')

            fig2.tight_layout()

            return summary, fig1, fig2

        if pricing_submit:
            try:
                summary_df, fig_orders, fig_revenue = analyze_pricing_impact(
                    df, column, threshold_price, threshold_value, drop_off_rate, fiscal_years
                )
                st.markdown("### 💡 Estimated Impact Summary")
                st.dataframe(summary_df)
                st.markdown("### 📊 Orders Breakdown")
                st.pyplot(fig_orders)
                st.markdown("### 💶 Revenue Impact")
                st.pyplot(fig_revenue)
            except Exception as e:
                st.error(f"❌ Error:\n\n{e}")
