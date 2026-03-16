# Tourism Pricing Analytics: Competitor Clustering & Hedonic Price Benchmarking

### Summary
A machine learning pipeline with the purpose of providing pricing analytics for a particular tourism business in Crete. Two core modelling approaches are used. Firstly, clustering is used on property listing features (e.g. price, beach distance, amenities, distance to urban centres, pools, room sizes etc), to acquire a close-competitor set. Secondly, a hedonic pricing model is employed, which essentially is a regression model, and this is to glean a benchmark or approximate fair-market value. Data is scraped on a rolling basis from online travel agency listings for tourism properties in Crete, Greece. Time-varying features are required so to update regression estimates and most recent pricing. The ultimate goal is to use this information to feed a daily dashboard of competitor behaviour and fair market price that in turn informs pricing for the client business using the dashboard.

### Motivation
The client business has little information to inform pricing