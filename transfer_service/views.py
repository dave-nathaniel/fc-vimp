from django.shortcuts import render
from rest_framework import generics, permissions
from .models import SalesOrder, GoodsIssueNote, TransferReceiptNote
from .serializers import (
    SalesOrderSerializer, GoodsIssueNoteSerializer, TransferReceiptNoteSerializer
)

# Create your views here.

class SalesOrderListView(generics.ListAPIView):
    queryset = SalesOrder.objects.all()
    serializer_class = SalesOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

class SalesOrderDetailView(generics.RetrieveAPIView):
    queryset = SalesOrder.objects.all()
    serializer_class = SalesOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

class GoodsIssueNoteListView(generics.ListAPIView):
    queryset = GoodsIssueNote.objects.all()
    serializer_class = GoodsIssueNoteSerializer
    permission_classes = [permissions.IsAuthenticated]

class GoodsIssueNoteDetailView(generics.RetrieveAPIView):
    queryset = GoodsIssueNote.objects.all()
    serializer_class = GoodsIssueNoteSerializer
    permission_classes = [permissions.IsAuthenticated]

class TransferReceiptNoteListView(generics.ListAPIView):
    queryset = TransferReceiptNote.objects.all()
    serializer_class = TransferReceiptNoteSerializer
    permission_classes = [permissions.IsAuthenticated]

class TransferReceiptNoteDetailView(generics.RetrieveAPIView):
    queryset = TransferReceiptNote.objects.all()
    serializer_class = TransferReceiptNoteSerializer
    permission_classes = [permissions.IsAuthenticated]