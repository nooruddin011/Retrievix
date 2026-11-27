# Billing and Subscriptions

## Terminate a subscription
To cancel a plan, open Settings > Plan and choose Terminate subscription. The current period stays active until the renewal date, and no further invoices are generated afterwards. Unused credits are not refunded.

Via the API:

```python
client.subscriptions.terminate(subscription_id, at_period_end=True)
```

## Download invoices
Invoices and receipts are available as PDF under Settings > Billing history. Each invoice lists usage by project and region.

## Update payment method
Change the credit card on file under Settings > Billing > Payment method. The new card is used for the next renewal; a failed charge is retried three times over seven days.
