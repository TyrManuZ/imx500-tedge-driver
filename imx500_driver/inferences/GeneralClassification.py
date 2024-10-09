# automatically generated by the FlatBuffers compiler, do not modify

# namespace: SmartCamera

import flatbuffers
from flatbuffers.compat import import_numpy
np = import_numpy()

class GeneralClassification(object):
    __slots__ = ['_tab']

    @classmethod
    def GetRootAs(cls, buf, offset=0):
        n = flatbuffers.encode.Get(flatbuffers.packer.uoffset, buf, offset)
        x = GeneralClassification()
        x.Init(buf, n + offset)
        return x

    @classmethod
    def GetRootAsGeneralClassification(cls, buf, offset=0):
        """This method is deprecated. Please switch to GetRootAs."""
        return cls.GetRootAs(buf, offset)
    # GeneralClassification
    def Init(self, buf, pos):
        self._tab = flatbuffers.table.Table(buf, pos)

    # GeneralClassification
    def ClassId(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(4))
        if o != 0:
            return self._tab.Get(flatbuffers.number_types.Uint32Flags, o + self._tab.Pos)
        return 0

    # GeneralClassification
    def Score(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(6))
        if o != 0:
            return self._tab.Get(flatbuffers.number_types.Float32Flags, o + self._tab.Pos)
        return 0.0

def GeneralClassificationStart(builder):
    builder.StartObject(2)

def Start(builder):
    GeneralClassificationStart(builder)

def GeneralClassificationAddClassId(builder, classId):
    builder.PrependUint32Slot(0, classId, 0)

def AddClassId(builder, classId):
    GeneralClassificationAddClassId(builder, classId)

def GeneralClassificationAddScore(builder, score):
    builder.PrependFloat32Slot(1, score, 0.0)

def AddScore(builder, score):
    GeneralClassificationAddScore(builder, score)

def GeneralClassificationEnd(builder):
    return builder.EndObject()

def End(builder):
    return GeneralClassificationEnd(builder)
